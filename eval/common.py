"""Shared by tune.py and run_eval.py: load the evidence store, apply a deadline, score an arm."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from pramaan.decide import decide
from pramaan.types import Evidence, Policy, Values, Verdict

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data" / "evidence.jsonl"
HUMAN_EVIDENCE = ROOT / "data" / "human" / "evidence.jsonl"
FRESH_EVIDENCE = ROOT / "data" / "fresh" / "evidence.jsonl"
POLICY = ROOT / "data" / "policy.json"
RESULTS = ROOT / "results"
ALPHA, DELTA = 0.05, 0.05
LOCAL = "indicconformer-greedy"


@dataclass(frozen=True)
class Row:
    clip_id: str
    speaker: str
    condition: str
    truth: Values
    response_ms: float
    evidence: Evidence


def load(path: Path = EVIDENCE) -> tuple[list[Row], int]:
    raw = [json.loads(line) for line in path.read_text().splitlines()]
    typical = statistics.median(r["agent_response_ms"] for r in raw if r["agent_response_ms"])
    rows = [
        Row(
            r["clip_id"],
            r["speaker"],
            r["condition"],
            r["truth"],
            r["agent_response_ms"] or typical,
            Evidence(**r["evidence"]),
        )  # fmt: skip
        for r in raw
        if not r["agent_failed"]
    ]
    return rows, len(raw) - len(rows)


def tuning_rows() -> list[Row]:
    """Everything a policy may be chosen on: the tuning speakers' clips from both batches."""
    rows = split(load()[0])[0]
    if FRESH_EVIDENCE.exists():
        rows += split(load(FRESH_EVIDENCE)[0])[0]
    return rows


def split(rows: list[Row]) -> tuple[list[Row], list[Row]]:
    s = json.loads((ROOT / "data" / "splits.json").read_text())
    return [r for r in rows if r.speaker in s["tune"]], [r for r in rows if r.speaker in s["test"]]


def within(
    row: Row, deadline_ms: float | None, drop_families: frozenset[str] = frozenset(), witness: bool = True
) -> Evidence:
    """The evidence the live system would have held at tool call + deadline: late sources become absent.

    Recorded latencies are measured from the start of each request, which live is the end of the caller's turn.
    """
    ev = row.evidence
    cutoff = None if deadline_ms is None else row.response_ms + deadline_ms
    keep, absent = [], list(ev.absent_sources)
    for h in ev.hypotheses:
        late = cutoff is not None and h.latency_ms > cutoff
        if late or h.family in drop_families or (not witness and h.source == LOCAL):
            absent.append(h.source)
        else:
            keep.append(h)
    return ev.model_copy(
        update={
            "hypotheses": tuple(keep),
            "absent_sources": tuple(absent),
            "witness": ev.witness if witness else (),
        }
    )


def wait_ms(row: Row, deadline_ms: float) -> float:
    """Time the tool call is held: until the last source lands or the deadline, whichever is first."""
    last = max((h.latency_ms for h in row.evidence.hypotheses), default=0.0)
    return max(0.0, min(last, row.response_ms + deadline_ms) - row.response_ms)


@dataclass(frozen=True)
class Outcome:
    executed: bool  # acted without asking the caller
    wrong: bool  # the value the arm would act on differs from the truth
    score: float = 1.0  # the arm's own confidence, for risk-coverage curves; -1 when it can never pass


def guard(row: Row, policy: Policy, **kw: object) -> Outcome:
    ev = within(row, policy.deadline_ms, **kw)  # type: ignore[arg-type]
    d = decide(ev, policy.model_copy(update={"accept_threshold": 0.0}))
    if d.verdict != Verdict.PASS:
        return Outcome(False, dict(ev.proposed) != row.truth, -1.0)
    return Outcome(d.score >= policy.accept_threshold, dict(d.execute) != row.truth, d.score)


def hyp(row: Row, source: str) -> Values | None:
    return next((dict(h.values) for h in row.evidence.hypotheses if h.source == source), None)
