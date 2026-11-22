"""decide(evidence, policy) -> Decision. Pure: no network, clock, randomness or environment.

Only the arguments the agent proposed are guarded; a value the caller said but the agent did not use is
not ours to act on.

Reason codes:
  families_agree         PASS: hard predicates hold and score >= accept_threshold
  no_evidence            no non-agent recogniser returned anything this turn
  invented               recognisers returned, but none heard any value for this slot
  malformed              proposed value is not a well-formed value for its slot (e.g. a 9-digit phone)
  insufficient_families  fewer than policy.min_families families support the proposed value
  witness_absent         require_witness and the witness did not score the proposed value
  witness_prefers_other  witness prefers another candidate by more than policy.witness_llr_min nats
  below_threshold        predicates hold but the score is under accept_threshold
  proposed_unsupported   no family supports the proposed value (ASK among alternatives when 2-3 exist)
  mismatch               no family supports the proposed value and exactly one alternative is plausible
  too_many_candidates    more than three plausible values: a forced choice would not help
  repaired               PASS with a different value: the one alternative that passes every test, when no
                         family heard a third value
  repaired_omission      PASS with a value added: the agent left the slot out and the evidence supplies it
  omitted                the agent left out a slot that enough families agree the caller stated
"""

from __future__ import annotations

import re

from . import question
from .lattice import (
    AGENT_FAMILY,
    SlotLattice,
    build,
    canon,
    differing_positions,
    is_valid,
    key,
    sorted_hypotheses,
)
from .score import features, posterior, score, witness_for, witness_llr, witness_posterior
from .types import SLOTS, Asked, Decision, Evidence, Policy, Slot, SlotDecision, Value, Verdict

# Scripts an acoustic model covers (Devanagari, Telugu). A turn written in none of them was spoken in English.
_NATIVE = re.compile("[ऀ-ॿఀ-౿]")
# A value is offered in a question if some family mostly heard it, or the witness clearly backs it.
PLAUSIBLE_MIN_POSTERIOR = 0.05
PLAUSIBLE_MIN_SUPPORT = 0.5
PLAUSIBLE_MIN_WITNESS = 0.2
MAX_OPTIONS = 3
_SEVERITY = {Verdict.PASS: 0, Verdict.ASK: 1, Verdict.BLOCK: 2}


def _failing_predicate(
    lat: SlotLattice, f: dict[str, float], llr: float | None, policy: Policy
) -> str | None:
    p = lat.proposed
    assert p is not None
    if lat.support_weight(p) == 0.0:
        return "proposed_unsupported"
    if f["n_support"] < policy.min_families:
        return "insufficient_families"
    if policy.require_witness:
        if f["witness_absent"]:
            return "witness_absent"
        if llr is not None and llr < -policy.witness_llr_min:
            return "witness_prefers_other"
    return None


def _judge_slot(evidence: Evidence, slot: Slot, policy: Policy) -> SlotDecision:
    lat = build(evidence, slot, policy.max_candidates)
    raw = evidence.proposed.get(slot)
    p = lat.proposed
    w = witness_for(evidence, slot)
    llr = witness_llr(w, p)
    post = posterior(evidence, lat)
    ranked = tuple(sorted(lat.candidates, key=lambda c: (-post.get(key(c), 0.0), key(c))))
    common = {
        "slot": slot,
        "proposed": p if p is not None else (raw if isinstance(raw, int | str) else None),
        "posterior": post,
        "witness_llr": round(llr, 9) if llr is not None else None,
    }

    if not is_valid(slot, p):
        return SlotDecision(verdict=Verdict.BLOCK, reason="malformed", candidates=ranked, **common)
    assert p is not None
    if not lat.families_present:
        return SlotDecision(verdict=Verdict.BLOCK, reason="no_evidence", candidates=ranked, **common)
    if not lat.families_heard:
        return SlotDecision(verdict=Verdict.BLOCK, reason="invented", candidates=ranked, **common)

    f = features(evidence, lat, slot, policy)
    s = score(f, policy)
    common |= {"score": s, "supporting_families": lat.supporting_families(p)}
    failing = _failing_predicate(lat, f, llr, policy)
    if failing is None and s >= policy.accept_threshold:
        return SlotDecision(
            verdict=Verdict.PASS,
            reason="families_agree",
            final=p,
            candidates=ranked,
            contested_positions=differing_positions(ranked[:2]),
            **common,
        )
    reason = failing or "below_threshold"

    wpost = witness_posterior(w, lat)
    plausible = [
        c
        for c in ranked
        if lat.support_weight(c) >= PLAUSIBLE_MIN_SUPPORT
        or (
            post.get(key(c), 0.0) >= PLAUSIBLE_MIN_POSTERIOR
            and wpost.get(key(c), 0.0) >= PLAUSIBLE_MIN_WITNESS
        )
    ]
    if 2 <= len(plausible) <= MAX_OPTIONS:
        options = tuple(plausible)
        return SlotDecision(
            verdict=Verdict.ASK,
            reason=reason,
            candidates=options,
            contested_positions=differing_positions(options),
            **common,
        )
    if len(plausible) > MAX_OPTIONS:
        reason = "too_many_candidates"
    elif len(plausible) == 1 and plausible[0] != p and reason == "proposed_unsupported":
        reason = "mismatch"
    return SlotDecision(
        verdict=Verdict.BLOCK,
        reason=reason,
        candidates=ranked,
        contested_positions=lat.contested_positions,
        **common,
    )


def _repair(
    evidence: Evidence, slot: Slot, policy: Policy, options: tuple[Value, ...]
) -> SlotDecision | None:
    """The one alternative that passes every test, judged exactly as if the agent had proposed it."""
    passing = []
    for c in options:
        if not is_valid(slot, c):
            continue
        swapped = evidence.model_copy(update={"proposed": {**evidence.proposed, slot: c}})
        alt = _judge_slot(swapped, slot, policy)
        if alt.verdict == Verdict.PASS:
            passing.append(alt)
    return passing[0] if len(passing) == 1 else None


def decide_slot(evidence: Evidence, slot: Slot, policy: Policy) -> SlotDecision:
    sd = _judge_slot(evidence, slot, policy)
    # A repair overrules the agent, so it is allowed only when no recogniser family heard the agent's value.
    # If one did, the evidence is split and the caller decides.
    if sd.verdict == Verdict.PASS or not policy.repair or sd.supporting_families:
        return sd
    fix = _repair(evidence, slot, policy, tuple(c for c in sd.candidates if c != sd.proposed))
    if fix is None or fix.final is None:
        return sd
    # Nor when a whole family heard a third value: on the tuning speakers 2 of 13 such repairs were wrong,
    # against 0 of 86 where every family that disagreed with the agent agreed with each other.
    lat = build(evidence, slot, policy.max_candidates)
    rivals = (c for c in lat.candidates if c != fix.final and is_valid(slot, c))
    if any(lat.supporting_families(c) for c in rivals):
        return sd
    return fix.model_copy(update={"proposed": sd.proposed, "reason": "repaired", "candidates": sd.candidates})


def _omitted(evidence: Evidence, slot: Slot, policy: Policy) -> SlotDecision | None:
    lat = build(evidence, slot, policy.max_candidates)
    agreed = [c for c in lat.candidates if len(lat.supporting_families(c)) >= max(policy.min_families, 2)]
    if len(agreed) != 1:
        return None
    fix = _repair(evidence, slot, policy, (agreed[0],)) if policy.repair else None
    if fix is not None:
        return fix.model_copy(update={"proposed": None, "reason": "repaired_omission"})
    return SlotDecision(
        slot=slot,
        proposed=None,
        verdict=Verdict.BLOCK,
        reason="omitted",
        candidates=(agreed[0],),
        supporting_families=lat.supporting_families(agreed[0]),
    )


def spoken_in_english(evidence: Evidence) -> bool:
    """True when OpenAI's transcribers answered and none of them wrote any Indic script."""
    texts = [h.text for h in evidence.hypotheses if h.family == "openai-transcribe" and h.text.strip()]
    return bool(texts) and not any(_NATIVE.search(t) for t in texts)


def resolve_answer(evidence: Evidence, policy: Policy, asked: Asked) -> Evidence:
    """Evidence for the caller's answer to a forced choice, with a short answer read as the option it names.

    A real caller says "saat", not the whole number again. The option is taken only when enough independent
    families name it and none names or hears another; otherwise the evidence comes back unchanged.
    """
    picks: dict[str, set[Value | None]] = {}
    for h in evidence.hypotheses:
        if h.family == AGENT_FAMILY:
            continue
        heard = canon(asked.slot, h.values.get(asked.slot))
        if heard is not None and heard not in asked.options:
            return evidence
        picks.setdefault(h.family, set()).add(question.pick(asked.slot, asked.options, h.text, heard))
    named = {fam: {v for v in vals if v is not None} for fam, vals in picks.items()}
    chosen = {v for vals in named.values() for v in vals}
    backers = [fam for fam, vals in named.items() if vals]
    if len(chosen) != 1 or len(backers) < max(policy.min_families, 2):
        return evidence
    winner = next(iter(chosen))
    hyps = tuple(
        h.model_copy(update={"values": {**h.values, asked.slot: winner}})
        if h.family in backers and question.pick(asked.slot, asked.options, h.text, h.values.get(asked.slot)) == winner
        else h
        for h in evidence.hypotheses
    )  # fmt: skip
    return evidence.model_copy(
        update={"hypotheses": hyps, "proposed": {**evidence.proposed, asked.slot: winner}}
    )


def decide(evidence: Evidence, policy: Policy) -> Decision:
    frozen = policy
    if policy.language_aware and spoken_in_english(evidence):
        evidence = evidence.model_copy(
            update={
                "hypotheses": tuple(h for h in evidence.hypotheses if h.family != "ai4bharat"),
                "witness": (),
            }
        )
        policy = policy.model_copy(update={"require_witness": False})
    evidence = evidence.model_copy(update={"hypotheses": sorted_hypotheses(evidence.hypotheses)})
    slots = tuple(decide_slot(evidence, s, policy) for s in SLOTS if s in evidence.proposed)
    if policy.guard_omissions and evidence.proposed:
        missing = (_omitted(evidence, s, policy) for s in SLOTS if s not in evidence.proposed)
        slots += tuple(sd for sd in missing if sd is not None)
    if not slots:
        return Decision(verdict=Verdict.PASS, slots=(), score=1.0, policy_hash=frozen.hash)
    execute = {sd.slot: sd.final for sd in slots if sd.final is not None}
    verdict = max((sd.verdict for sd in slots), key=_SEVERITY.__getitem__)
    # The question goes to the least certain slot among those carrying the worst verdict.
    target = None
    if verdict != Verdict.PASS:
        target = min((sd for sd in slots if sd.verdict == verdict), key=lambda sd: sd.score)
    return Decision(
        verdict=verdict,
        slots=slots,
        score=min(sd.score for sd in slots),
        execute=execute if verdict == Verdict.PASS else {},
        question=question.phrase(target) if target else None,
        question_slot=target.slot if target else None,
        policy_hash=frozen.hash,
    )
