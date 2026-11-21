"""Features of the evidence for one proposed slot value, a score in [0, 1], and a posterior over candidates.

Family support and witness presence are hard predicates applied in decide.py; here they only shape the score.

Fixed rule (used when policy.weights is empty), monotone in every piece of evidence:

    fam   = S / (n + 1)          S = summed family support for the proposed value, n = non-agent families present
    wit   = sigmoid(clip(llr))   if the witness scored the proposed value against an alternative, else 0.5
    score = valid * (0.6 * fam + 0.4 * wit) * (0.85 if a family's variants disagree else 1)

Adding a supporting family raises fam ((S+1)/(n+2) > S/(n+1) since S <= n) and touches nothing else.
Log-probabilities are left out of the fixed rule: a minimum over hypotheses can fall when a supporter is added.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from .lattice import AGENT_FAMILY, SlotLattice, canon, is_valid, key
from .types import Evidence, Policy, Slot, Value, WitnessScore

LLR_CLIP = 10.0
LOGPROB_FLOOR = -10.0
# Dirichlet pseudo-count so a candidate heard by nobody keeps a little family mass.
FAMILY_PRIOR = 0.5

FEATURES: tuple[str, ...] = (
    "support_frac",  # summed non-agent family support for proposed / non-agent families present
    "n_families",  # non-agent families present this turn
    "n_support",  # families where a majority of variants heard the proposed value
    "witness_llr",  # loglik(proposed) - max loglik(other scored value), clipped to +-LLR_CLIP; 0 if absent
    "witness_absent",  # 1 if no witness for this slot or it did not score the proposed value
    "witness_post",  # witness softmax of proposed over lattice candidates; 0 if absent
    "min_logprob",  # min value_min_logprob over supporting hypotheses that expose it, floored; 0 if absent
    "logprob_absent",
    "unstable",  # 1 if some family's variants heard different values
    "stability_absent",  # 1 if no family ran more than one variant
    "valid",  # proposed value is well formed for its slot
    "n_candidates",
)


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def witness_for(evidence: Evidence, slot: Slot) -> WitnessScore | None:
    ws = sorted(
        (w for w in evidence.witness if w.slot == slot), key=lambda w: (w.model, sorted(w.loglik.items()))
    )
    return ws[0] if ws else None


def witness_llr(witness: WitnessScore | None, proposed: Value | None) -> float | None:
    """Against every other value the witness scored, so the lattice cannot move it."""
    if witness is None or proposed is None or key(proposed) not in witness.loglik:
        return None
    others = [v for k, v in witness.loglik.items() if k != key(proposed)]
    if not others:
        return None
    return witness.loglik[key(proposed)] - max(others)


def _softmax(logits: Mapping[str, float]) -> dict[str, float]:
    if not logits:
        return {}
    top = max(logits.values())
    ex = {k: math.exp(v - top) for k, v in logits.items()}
    z = sum(ex.values())
    return {k: e / z for k, e in ex.items()}


def witness_posterior(witness: WitnessScore | None, lat: SlotLattice) -> dict[str, float]:
    if witness is None:
        return {}
    scored = {key(c): witness.loglik[key(c)] for c in lat.candidates if key(c) in witness.loglik}
    return _softmax(scored)


def posterior(evidence: Evidence, lat: SlotLattice) -> dict[str, float]:
    """Naive product of a family vote prior and the witness likelihood, over lattice candidates.

    Phones use the confusion-network path probability as the family prior so recombined digit strings
    get mass; other slots use smoothed family support. Candidates the witness did not score get the
    lowest loglik it gave any candidate: absence of acoustic evidence is not evidence for a value.
    """
    if not lat.candidates:
        return {}
    keys = [key(c) for c in lat.candidates]
    if lat.network is not None and lat.path_logprob:
        prior = {k: lat.path_logprob.get(k, min(lat.path_logprob.values())) for k in keys}
    else:
        prior = {
            k: math.log(lat.support_weight(c) + FAMILY_PRIOR)
            for k, c in zip(keys, lat.candidates, strict=True)
        }
    w = witness_for(evidence, lat.slot)
    scored = {k: w.loglik[k] for k in keys if w is not None and k in w.loglik}
    floor = min(scored.values()) if scored else 0.0
    logits = {k: prior[k] + scored.get(k, floor) for k in keys}
    return {k: round(p, 9) for k, p in _softmax(logits).items()}


def features(
    evidence: Evidence, lat: SlotLattice, slot: Slot, policy: Policy | None = None
) -> dict[str, float]:
    p = lat.proposed
    n = len(lat.families_present)
    s = lat.support_weight(p) if p is not None else 0.0
    w = witness_for(evidence, slot)
    llr = witness_llr(w, p)
    wpost = witness_posterior(w, lat)
    lps = [
        h.value_min_logprob[slot]
        for h in evidence.hypotheses
        if h.family != AGENT_FAMILY
        and p is not None
        and canon(slot, h.values.get(slot)) == p
        and slot in h.value_min_logprob
    ]
    return {
        "support_frac": s / n if n else 0.0,
        "n_families": float(n),
        "n_support": float(len(lat.supporting_families(p))) if p is not None else 0.0,
        "witness_llr": max(-LLR_CLIP, min(LLR_CLIP, llr)) if llr is not None else 0.0,
        "witness_absent": 0.0 if (w is not None and p is not None and key(p) in w.loglik) else 1.0,
        "witness_post": wpost.get(key(p), 0.0) if p is not None else 0.0,
        "min_logprob": max(LOGPROB_FLOOR, min(lps)) if lps else 0.0,
        "logprob_absent": 0.0 if lps else 1.0,
        "unstable": 1.0 if lat.unstable_families else 0.0,
        "stability_absent": 0.0 if lat.multi_variant_families else 1.0,
        "valid": 1.0 if is_valid(slot, p) else 0.0,
        "n_candidates": float(len(lat.candidates)),
    }


def fixed_rule(f: Mapping[str, float]) -> float:
    n = f["n_families"]
    s = f["support_frac"] * n
    fam = s / (n + 1.0)
    wit = 0.5 if f["witness_absent"] else sigmoid(f["witness_llr"])
    return f["valid"] * (0.6 * fam + 0.4 * wit) * (0.85 if f["unstable"] else 1.0)


def score(f: Mapping[str, float], policy: Policy) -> float:
    if not policy.weights:
        return round(fixed_rule(f), 9)
    unknown = set(policy.weights) - set(FEATURES)
    if unknown:
        raise KeyError(f"policy weights name unknown features: {sorted(unknown)}")
    z = policy.bias + sum(wt * f[name] for name, wt in sorted(policy.weights.items()))
    return round(sigmoid(z), 9)
