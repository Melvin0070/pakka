"""Every arm on the same test-speaker clips, from the committed evidence store. No model, key or network.

Writes results/headline.json (read by the UI) and results/table.md (pasted into the README).
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from pramaan.gate import cp_upper, ltt_select, risk_coverage, speaker_bound
from pramaan.pipeline import load_policy

from .common import (
    ALPHA,
    DELTA,
    FRESH2_EVIDENCE,
    FRESH_EVIDENCE,
    HUMAN_EVIDENCE,
    LOCAL,
    RESULTS,
    Outcome,
    Row,
    guard,
    hyp,
    load,
    split,
    tuning_rows,
    wait_ms,
)

# Assumption, not a measurement: one forced-choice question and its answer. Read-back of a whole action is
# longer in practice; using the same figure for both is generous to the read-back arm.
SECONDS_PER_QUESTION = 4.0
CASCADE = "gpt-transcribe+hints"
SECOND = "verbx-vocaline"
SARVAM = "saaras"


def bare(row: Row) -> Outcome:
    return Outcome(True, dict(row.evidence.proposed) != row.truth)


def cascade(source: str) -> Callable[[Row], Outcome]:
    def arm(row: Row) -> Outcome:
        v = hyp(row, source)
        return Outcome(True, v != row.truth)

    return arm


def logprob_gate(row: Row) -> Outcome:
    h = next((h for h in row.evidence.hypotheses if h.source == "gpt-4o-transcribe"), None)
    if h is None:
        return Outcome(False, True, -1.0)
    lps = [h.value_min_logprob.get(s) for s in h.values]
    score = (
        math.exp(min(lp for lp in lps if lp is not None))
        if lps and all(lp is not None for lp in lps)
        else 0.0
    )
    return Outcome(True, dict(h.values) != row.truth, score)


def two_model(second: str) -> Callable[[Row], Outcome]:
    def arm(row: Row) -> Outcome:
        a, b = hyp(row, CASCADE), hyp(row, second)
        return Outcome(a is not None and a == b, a != row.truth)

    return arm


def read_back(row: Row) -> Outcome:
    return Outcome(False, dict(row.evidence.proposed) != row.truth)


def thresholded(arm: Callable[[Row], Outcome], t: float) -> Callable[[Row], Outcome]:
    def gated(row: Row) -> Outcome:
        o = arm(row)
        return Outcome(o.executed and o.score >= t, o.wrong, o.score)

    return gated


def summarise(rows: list[Row], arm: Callable[[Row], Outcome]) -> dict:
    outs = [arm(r) for r in rows]
    n = len(outs)
    asked = sum(not o.executed for o in outs)
    return {
        "n": n,
        "wrong_silent": sum(o.executed and o.wrong for o in outs),
        "asked": asked,
        "asked_needed": sum(not o.executed and o.wrong for o in outs),
        "accepted": n - asked,
        "caller_seconds": round(asked / n * SECONDS_PER_QUESTION, 2) if n else 0.0,
    }


def curve(rows: list[Row], arm: Callable[[Row], Outcome]) -> list[list[float]]:
    pts = risk_coverage([(o.score, o.wrong) for o in map(arm, rows)], DELTA)
    return [[round(p.coverage, 4), round(p.risk, 4), round(p.threshold, 4)] for p in pts if p.threshold >= 0]


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def main() -> None:
    rows, agent_failed = load()
    tune, test = split(rows)
    # Human recordings are test only: thresholds and the policy still come from the synthetic tuning speakers.
    human, fresh2 = "--human" in sys.argv, "--fresh2" in sys.argv
    fresh = "--fresh" in sys.argv or fresh2
    tune = tuning_rows()
    if human:
        test, agent_failed = load(HUMAN_EVIDENCE)
    elif fresh:
        # The locked batch: test speakers, new values, scored after the policy was frozen.
        rows, agent_failed = load(FRESH2_EVIDENCE if fresh2 else FRESH_EVIDENCE)
        test = split(rows)[1]
    kind = "human" if human else "synthetic"
    stem = "human" if human else "fresh2" if fresh2 else "fresh" if fresh else None
    policy = load_policy()
    has_second = any(hyp(r, SECOND) is not None for r in test)
    second = SECOND if has_second else LOCAL

    lp_threshold = ltt_select([(o.score, o.wrong) for o in map(logprob_gate, tune)], ALPHA, DELTA).threshold
    lp_arm = thresholded(logprob_gate, lp_threshold if lp_threshold is not None else 2.0)

    def pramaan(row: Row) -> Outcome:
        return guard(row, policy)

    arms: list[tuple[str, str, str, Callable[[Row], Outcome], bool]] = [
        ("A", "Realtime model alone", "gpt-realtime-2.1 hears the audio and calls the tool", bare, False),
        ("B", "Transcribe, then fill the form", "gpt-transcribe with a domain prompt, then typed normalisation", cascade(CASCADE), False),
        ("B-LP", "Trust one model's confidence", "gpt-4o-transcribe token log-probabilities, threshold set the same way", lp_arm, False),
        ("B-2M", "Ask when two models disagree", f"{CASCADE} against {second}", two_model(second), False),
        ("A-RB", "Read everything back", "Confirm every action with the caller", read_back, False),
        ("P", "Pramaan", "Hold the realtime model's action until the evidence supports it", pramaan, True),
    ]  # fmt: skip
    if has_second:
        arms.insert(2, ("V", "Second vendor, then fill the form", f"{SECOND}, then typed normalisation", cascade(SECOND), False))  # fmt: skip
    if any(hyp(r, SARVAM) is not None for r in test):
        at = next(i for i, a in enumerate(arms) if a[0] == "B-LP")
        arms.insert(at, ("S", "Sarvam, then fill the form", "Sarvam saaras:v3, then typed normalisation", cascade(SARVAM), False))  # fmt: skip
        at = next(i for i, a in enumerate(arms) if a[0] == "A-RB")
        arms.insert(at, ("B-2S", "Ask when OpenAI and Sarvam disagree", f"{CASCADE} against {SARVAM}", two_model(SARVAM), False))  # fmt: skip

    out_arms = []
    for arm_id, name, how, fn, ours in arms:
        s = summarise(test, fn)
        out_arms.append({"id": arm_id, "name": name, "how": how, "ours": ours, **s})
    waits = sorted(wait_ms(r, policy.deadline_ms) for r in test)
    p_arm = next(a for a in out_arms if a["id"] == "P")
    p_arm["added_latency_p50_ms"] = round(statistics.median(waits))
    p_arm["added_latency_p95_ms"] = round(waits[int(0.95 * (len(waits) - 1))])

    accepted = [(r, o) for r, o in ((r, pramaan(r)) for r in test) if o.executed]
    n_acc, k = len(accepted), sum(o.wrong for _, o in accepted)
    by_speaker: dict[str, list[bool]] = defaultdict(list)
    for r, o in accepted:
        by_speaker[r.speaker].append(o.wrong)
    sb = speaker_bound(by_speaker, DELTA)
    certificate = {
        "n_accepted": n_acc,
        "k_wrong": k,
        "upper_bound": round(cp_upper(k, n_acc, DELTA), 4) if n_acc else None,
        "confidence": 1 - DELTA,
        "n_speakers": len(by_speaker),
        "speaker_level_bound": round(sb.upper, 4),
        "speakers_with_error": sb.speakers_with_error,
        "scope": "first-pass decisions on test speakers; actions held for a question are not covered",
    }

    ablations = []
    variants: list[tuple[str, Callable[[Row], Outcome]]] = [
        ("Pramaan as frozen", pramaan),
        ("without the acoustic model", lambda r: guard(r, policy.model_copy(update={"require_witness": False}), witness=False)),
        ("OpenAI transcribers only", lambda r: guard(r, policy.model_copy(update={"min_families": 1, "require_witness": False}), witness=False, drop_families=frozenset({"verbx", "elevenlabs", "sarvam"}))),
        ("acoustic model as the only check", lambda r: guard(r, policy.model_copy(update={"min_families": 1}), drop_families=frozenset({"verbx", "elevenlabs", "sarvam"}))),
        ("without the language check (acoustic model also judges English)", lambda r: guard(r, policy.model_copy(update={"language_aware": False}))),
        ("without Sarvam", lambda r: guard(r, policy, drop_families=frozenset({"sarvam"}))),
        ("without the dropped-value check", lambda r: guard(r, policy.model_copy(update={"guard_omissions": False}))),
        ("no deadline (wait for every source)", lambda r: guard(r, policy.model_copy(update={"deadline_ms": 60_000.0}))),
        ("deadline 300 ms", lambda r: guard(r, policy.model_copy(update={"deadline_ms": 300.0}))),
    ]  # fmt: skip
    for name, fn in variants:
        s = summarise(test, fn)
        ablations.append(
            {"name": name, **{k2: s[k2] for k2 in ("n", "wrong_silent", "asked", "asked_needed")}}
        )

    by_slot: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in test:
        for slot, truth in r.truth.items():
            by_slot[slot][0] += 1
            by_slot[slot][1] += r.evidence.proposed.get(slot) != truth
    by_condition = {
        c: {"A": summarise(sub, bare), "P": summarise(sub, pramaan)}
        for c in sorted({r.condition for r in test})
        if (sub := [r for r in test if r.condition == c])
    }

    headline = {
        "dataset": {
            "kind": "human-recorded" if human else "synthetic-tts",
            "n_actions": len(test),
            "n_speakers": len({r.speaker for r in test}),
            "batch": "locked: new values, scored once after the policy was frozen" if fresh else "first",
            "condition": "laptop microphone, then 8 kHz AMR-NB + A-law phone channel"
            if human
            else "8 kHz AMR-NB + A-law phone channel, part with babble noise",
            "tune_actions": len(tune),
            "tune_speakers": len({r.speaker for r in tune}),
            "agent_failed_excluded": agent_failed,
        },
        "policy_hash": policy.hash,
        "policy": policy.model_dump(),
        "alpha": ALPHA,
        "arms": out_arms,
        "certificate": certificate,
        "risk_coverage": {"P": curve(test, pramaan), "B-LP": curve(test, logprob_gate)},
        "ablations": ablations,
        "agent_error_by_slot": {s: {"n": n, "wrong": w} for s, (n, w) in sorted(by_slot.items())},
        "by_condition": by_condition,
        "assumptions": {"seconds_per_question": SECONDS_PER_QUESTION},
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (f"{stem}.json" if stem else "headline.json")).write_text(
        json.dumps(headline, indent=1, ensure_ascii=False) + "\n"
    )

    lines = [
        f"{len(test)} actions, {headline['dataset']['n_speakers']} held-out {kind} speakers, phone-grade audio. Policy `{policy.hash}`.",
        "",
        "| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |",
        "|---|---|---|---|---|",
    ]
    for a in out_arms:
        n = a["n"]
        lines.append(
            f"| {'**' if a['ours'] else ''}{a['name']}{'**' if a['ours'] else ''} ({a['id']}) | {a['wrong_silent']} ({pct(a['wrong_silent'] / n)}) "
            f"| {a['asked']} ({pct(a['asked'] / n)}) | {a['asked_needed']} | {a['accepted']} |"
        )
    lines += [
        "",
        f"Certificate: of {n_acc} actions Pramaan let through, {k} were wrong; one-sided 95% Clopper-Pearson upper bound "
        f"{pct(certificate['upper_bound'] or 0)}. Speaker-level: {sb.speakers_with_error} of {sb.speakers} speakers had any silent error "
        f"(bound {pct(sb.upper)}). Added hold p50 {p_arm['added_latency_p50_ms']} ms, p95 {p_arm['added_latency_p95_ms']} ms.",
        "",
        "| Ablation | Wrong and acted on | Caller asked | of which wrong |",
        "|---|---|---|---|",
        *(f"| {a['name']} | {a['wrong_silent']} | {a['asked']} | {a['asked_needed']} |" for a in ablations),
    ]
    (RESULTS / (f"{stem}.md" if stem else "table.md")).write_text("\n".join(lines) + "\n")
    readme = RESULTS.parent / "README.md"
    mark = "results" if stem is None else stem
    if readme.exists() and f"<!-- {mark}:start -->" in (text := readme.read_text()):
        head, rest = text.split(f"<!-- {mark}:start -->", 1)
        tail = rest.split(f"<!-- {mark}:end -->", 1)[1]
        body = "\n".join(lines)
        readme.write_text(f"{head}<!-- {mark}:start -->\n{body}\n<!-- {mark}:end -->{tail}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
