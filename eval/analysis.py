"""Where Pramaan wins, ties and loses against the two-model baselines, and what it costs.

Everything here is read off the frozen policy's test-speaker outcomes; nothing is tuned. The matched-budget
rows move Pramaan's acceptance threshold after the fact, so they describe its risk-coverage curve and are not
certified operating points. Writes results/analysis.json and results/analysis.md, and the README block.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable

from pramaan.decide import decide
from pramaan.pipeline import load_policy
from pramaan.types import Verdict

from .common import EVIDENCE, RESULTS, ROOT, Outcome, Row, guard, hyp, load, split, within
from .run_eval import CASCADE, SARVAM, SECOND, bare, pct, summarise, two_model

PRICES = ROOT / "eval" / "prices.json"


def matched(outs: list[Outcome], base: dict) -> dict:
    """Pramaan's curve read at the baseline's question budget, and at the baseline's error count."""
    points = []
    for t in sorted({o.score for o in outs if o.executed}):
        acc = [o for o in outs if o.executed and o.score >= t]
        points.append((len(outs) - len(acc), sum(o.wrong for o in acc)))
    same_q = min((p for p in points if p[0] <= base["asked"]), key=lambda p: p[1], default=None)
    same_e = min((p for p in points if p[1] <= base["wrong_silent"]), key=lambda p: p[0], default=None)
    return {
        "baseline_asked": base["asked"],
        "baseline_wrong": base["wrong_silent"],
        "pramaan_wrong_at_no_more_questions": same_q[1] if same_q else None,
        "pramaan_asked_there": same_q[0] if same_q else None,
        "pramaan_asked_at_no_more_errors": same_e[0] if same_e else None,
        "pramaan_wrong_there": same_e[1] if same_e else None,
    }


def breakdown(rows: list[Row], key: Callable[[Row], str], arms: dict[str, Callable[[Row], Outcome]]) -> dict:
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    return {
        g: {"n": len(sub), **{a: {k: summarise(sub, fn)[k] for k in ("wrong_silent", "asked")} for a, fn in arms.items()}}
        for g, sub in sorted(groups.items())
    }  # fmt: skip


def main() -> None:
    rows, _ = load()
    _, test = split(rows)
    policy = load_policy()
    n = len(test)

    def pramaan(r: Row) -> Outcome:
        return guard(r, policy)

    outs = [pramaan(r) for r in test]
    two = {"B-2M": two_model(SECOND), "B-2S": two_model(SARVAM)}
    arms = {"A": bare, **two, "P": pramaan}
    base = {k: summarise(test, fn) for k, fn in two.items()}

    # What each approach does with the errors that matter.
    agent_wrong = [(r, o) for r, o in zip(test, outs, strict=True) if dict(r.evidence.proposed) != r.truth]
    fate = Counter(
        "repaired to the true value" if o.executed and not o.wrong else "caller asked" if not o.executed else "acted on, wrong"
        for _, o in agent_wrong
    )  # fmt: skip
    shared = [r for r in test if hyp(r, CASCADE) == hyp(r, SARVAM) and hyp(r, CASCADE) != r.truth]
    shared_fate = Counter(
        "acted on, wrong" if o.executed and o.wrong else "acted on, right" if o.executed else "caller asked"
        for o in map(pramaan, shared)
    )

    outage = {}
    for label, fam in (
        ("Sarvam", "sarvam"),
        ("VerbX", "verbx"),
        ("OpenAI transcription", "openai-transcribe"),
    ):
        s = summarise(test, lambda r, fam=fam: guard(r, policy, drop_families=frozenset({fam})))
        outage[label] = {k: s[k] for k in ("wrong_silent", "asked")}

    raw = {r["clip_id"]: r for r in map(json.loads, EVIDENCE.read_text().splitlines())}
    prompts = {
        p["id"]: p for p in map(json.loads, (ROOT / "data" / "prompts.jsonl").read_text().splitlines())
    }

    def prompt(r: Row) -> dict:
        return prompts[raw[r.clip_id]["prompt_id"]]

    by = {
        "condition": breakdown(test, lambda r: r.condition, arms),
        "language": breakdown(test, lambda r: prompt(r)["lang"], arms),
        "difficulty": breakdown(test, lambda r: "confusable" if prompt(r)["hard"] else "ordinary", arms),
        "values": breakdown(test, lambda r: "+".join(sorted(r.truth)), arms),
    }

    # Latency and cost per guarded action.
    lat: dict[str, list[float]] = defaultdict(list)
    for r in test:
        for h in r.evidence.hypotheses:
            lat[h.source].append(h.latency_ms)
    latency = {
        s: {"p50_ms": round(statistics.median(v)), "p90_ms": round(sorted(v)[int(0.9 * (len(v) - 1))])}
        for s, v in sorted(lat.items())
    }
    seconds = statistics.mean(raw[r.clip_id]["duration_s"] for r in test)
    cost = None
    if PRICES.exists():
        prices = json.loads(PRICES.read_text())
        per_min = {k: v for k, v in prices["usd_per_audio_minute"].items() if v is not None}
        cost = {
            "audio_seconds_per_action": round(seconds, 2),
            "usd_per_action_by_source": {k: round(v * seconds / 60, 5) for k, v in per_min.items()},
            "usd_per_1000_actions": round(1000 * sum(per_min.values()) * seconds / 60, 2),
            "not_priced": [k for k, v in prices["usd_per_audio_minute"].items() if v is None],
            "as_of": prices["as_of"],
            "sources": prices["sources"],
            "note": prices["note"],
        }

    questions = None
    if (RESULTS / "questions.json").exists():
        q = json.loads((RESULTS / "questions.json").read_text())
        questions = {k: v for k, v in q.items() if k != "actions"}

    verdicts = Counter(decide(within(r, policy.deadline_ms), policy).verdict for r in test)
    out = {
        "n": n,
        "policy_hash": policy.hash,
        "matched": {k: matched(outs, b) for k, b in base.items()},
        "agent_errors": {"n": len(agent_wrong), "fate": dict(fate)},
        "shared_transcriber_errors": {"n": len(shared), "two_model_baseline": "acted on, wrong", "pramaan": dict(shared_fate)},
        "vendor_outage": outage,
        "by": by,
        "latency": latency,
        "cost": cost,
        "questions": questions,
        "first_pass": {"ask": verdicts[Verdict.ASK], "block": verdicts[Verdict.BLOCK]},
    }  # fmt: skip
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")

    m = out["matched"]
    lines = [
        f"Read from the same {n} test actions and frozen policy. Not tuned; the matched rows move only Pramaan's "
        "acceptance threshold after the fact.",
        "",
        "| Against | Its result | Pramaan with no more questions | Pramaan with no more errors |",
        "|---|---|---|---|",
    ]
    names = {"B-2M": "gpt-transcribe vs VerbX", "B-2S": "gpt-transcribe vs Sarvam"}
    for k, v in m.items():
        q = (
            f"{v['pramaan_wrong_at_no_more_questions']} wrong, {v['pramaan_asked_there']} asked"
            if v["pramaan_asked_there"] is not None
            else "not reachable"
        )
        e = (
            f"{v['pramaan_wrong_there']} wrong, {v['pramaan_asked_at_no_more_errors']} asked"
            if v["pramaan_asked_at_no_more_errors"] is not None
            else "not reachable"
        )
        lines.append(
            f"| {names[k]} ({k}) | {v['baseline_wrong']} wrong, {v['baseline_asked']} asked | {q} | {e} |"
        )
    lines += [
        "",
        f"Of the {len(agent_wrong)} actions where the realtime model's value was wrong: "
        + "; ".join(f"{c} {k}" for k, c in fate.most_common())
        + ".",
        f"Of the {len(shared)} actions where gpt-transcribe and Sarvam agreed on a wrong value (the two-model "
        "baseline acts on all of them): Pramaan "
        + "; ".join(f"{c} {k}" for k, c in shared_fate.most_common())
        + ".",
        "",
        "| If a vendor is down | Wrong and acted on | Caller asked |",
        "|---|---|---|",
        *(f"| Pramaan without {k} | {v['wrong_silent']} | {v['asked']} |" for k, v in outage.items()),
        f"| Two-model baseline without Sarvam (falls back to VerbX) | {base['B-2M']['wrong_silent']} | {base['B-2M']['asked']} |",
        "",
        "| Slice | Actions | Realtime alone wrong | Sarvam baseline wrong / asked | Pramaan wrong / asked |",
        "|---|---|---|---|---|",
    ]
    for title, groups in by.items():
        for g, v in groups.items():
            lines.append(
                f"| {title}: {g} | {v['n']} | {v['A']['wrong_silent']} ({pct(v['A']['wrong_silent'] / v['n'])}) "
                f"| {v['B-2S']['wrong_silent']} / {v['B-2S']['asked']} | {v['P']['wrong_silent']} / {v['P']['asked']} |"
            )
    lines += ["", "| Source | Latency p50 | p90 |", "|---|---|---|"]
    lines += [f"| {s} | {v['p50_ms']} ms | {v['p90_ms']} ms |" for s, v in latency.items()]
    if cost:
        lines += [
            "",
            f"Checking one action ({cost['audio_seconds_per_action']} s of audio) costs about "
            f"${cost['usd_per_1000_actions'] / 1000:.4f} in recogniser calls at list prices as of {cost['as_of']} "
            f"(${cost['usd_per_1000_actions']:.2f} per 1,000 actions; {cost['note']}).",
        ]
    if questions:
        o = questions["outcomes"]
        lines += [
            "",
            f"After a question ({questions['n']} asked test actions replayed live, synthetic cooperative answers): "
            + "; ".join(f"{c} {k.replace('_', ' ')}" for k, c in o.items())
            + f". Mean questions per asked action {questions['questions_per_action_mean']}.",
        ]
    body = "\n".join(lines)
    (RESULTS / "analysis.md").write_text(body + "\n")
    readme = ROOT / "README.md"
    if "<!-- analysis:start -->" in (text := readme.read_text()):
        head, rest = text.split("<!-- analysis:start -->", 1)
        tail = rest.split("<!-- analysis:end -->", 1)[1]
        readme.write_text(f"{head}<!-- analysis:start -->\n{body}\n<!-- analysis:end -->{tail}")
    print(body)


if __name__ == "__main__":
    main()
