"""Turn raw recogniser output and the acoustic model's frame posteriors into an Evidence object.

Shared by the live pipeline and the offline evaluation, so both judge exactly the same thing.
Deterministic given its inputs: the acoustic log-probabilities are passed in, never computed here.
"""

from __future__ import annotations

import re
from typing import Protocol

import numpy as np

from . import confusables, normalise
from .lattice import canon, is_valid, key
from .render import renderings
from .types import SLOTS, Evidence, Hypothesis, Slot, Value, Values, WitnessScore

GREEDY_SOURCE = "indicconformer-greedy"
_DEVANAGARI = re.compile("[ऀ-ॿ]")
# Vendor transcripts first: when the open model's own decode garbles part of a number, the piece left
# outside the parsed span ends up in the context and tilts the score towards the garbled value.
_CONTEXT_ORDER = (
    "verbx-vocaline",
    "gpt-transcribe+hints",
    "gpt-transcribe",
    "gpt-4o-transcribe",
    "saaras",
    "scribe",
    GREEDY_SOURCE,
)
MAX_CONTEXTS = 2
# The open model votes for a value only when it beats every rival by this many nats; otherwise it abstains.
VOTE_MARGIN = 3.0
MAX_CANDIDATES = 8


class Scorer(Protocol):
    def greedy(self, log_probs: np.ndarray) -> str: ...

    def score_slot(
        self,
        log_probs: np.ndarray,
        slot: Slot,
        candidates: dict[str, list[str]],
        context: tuple[str, str] | None = None,
    ) -> WitnessScore: ...


def _token_spans(h: Hypothesis) -> list[tuple[int, int, float]]:
    spans: list[tuple[int, int, float]] = []
    cursor = 0
    for w in h.words:
        piece = w.text.strip()
        if not piece or w.logprob is None:
            continue
        at = h.text.find(piece, cursor)
        if at < 0:
            continue
        spans.append((at, at + len(piece), w.logprob))
        cursor = at + len(piece)
    return spans


def typed(h: Hypothesis) -> Hypothesis:
    """Fill `values` and, where the vendor exposes token log-probabilities, the weakest token under each value."""
    values: Values = {}
    min_lp: dict[str, float] = {}
    spans = _token_spans(h)
    for e in normalise.extract(h.text):
        if e.slot in values:
            continue
        values[e.slot] = e.value
        under = [lp for s, t, lp in spans if s < e.end and t > e.start]
        if under:
            min_lp[e.slot] = min(under)
    return h.model_copy(update={"values": values, "value_min_logprob": min_lp})


def _contexts(hyps: list[Hypothesis], slot: Slot) -> list[tuple[str, str] | None]:
    by_source = {h.source: h for h in hyps}
    out: list[tuple[str, str] | None] = []
    for name in _CONTEXT_ORDER:
        h = by_source.get(name)
        if h is None or not _DEVANAGARI.search(h.text):
            continue
        e = next((e for e in normalise.extract(h.text) if e.slot == slot), None)
        if e is None:
            continue
        ctx = (h.text[: e.start].strip(), h.text[e.end :].strip())
        if ctx not in out:
            out.append(ctx)
        if len(out) == MAX_CONTEXTS:
            break
    return out or [None]


def acoustic_vote(free: Hypothesis, witness: list[WitnessScore]) -> Hypothesis:
    """The open model's hypothesis: its free decode for the text, constrained scoring for the values.

    Ranking a closed candidate set is far more accurate than free decoding, so where it scored a slot
    the vote is the winner if it is clear and nothing if it is not."""
    values = dict(free.values)
    for w in witness:
        ranked = sorted(w.loglik.items(), key=lambda kv: (-kv[1], kv[0]))
        values.pop(w.slot, None)
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] >= VOTE_MARGIN:
            best = ranked[0][0]
            values[w.slot] = best if w.slot in ("phone", "weekday") else int(best)
    return free.model_copy(update={"values": values})


def candidates(proposed: Values, hyps: list[Hypothesis], slot: Slot) -> list[Value]:
    out: dict[str, Value] = {}
    for v in [proposed.get(slot), *(h.values.get(slot) for h in hyps)]:
        c = canon(slot, v)
        # A malformed phone is still scored: the guard should see how the audio rates what the agent wrote.
        if c is not None and (is_valid(slot, c) or slot == "phone"):
            out.setdefault(key(c), c)
    return list(out.values())[:MAX_CANDIDATES]


def witness_scores(
    scorer: Scorer, log_probs: np.ndarray, proposed: Values, hyps: list[Hypothesis], free: Hypothesis
) -> list[WitnessScore]:
    scores: list[WitnessScore] = []
    for slot in SLOTS:
        # Slots the agent left out are scored too, so a dropped value can be restored on evidence.
        # A malformed value (a nine-digit phone) is scored only when it is what the agent wrote. As a rival
        # it wins on length alone: fewer words to match, so a higher likelihood than any complete number.
        mine = canon(slot, proposed.get(slot))
        cands = [c for c in candidates(proposed, hyps, slot) if is_valid(slot, c) or c == mine]
        rivals = [n for c in cands if is_valid(slot, c) for n in confusables.neighbours(slot, c)]
        pool = {key(c): c for c in [*cands, *rivals]}
        forms = {k: renderings(slot, c) if is_valid(slot, c) else [str(c)] for k, c in pool.items()}
        if not forms:
            continue
        # Each candidate keeps its best context: a full-sentence likelihood, comparable across contexts.
        contexts = [c for c in _contexts([free, *hyps], slot) if c is not None]
        if not contexts:
            # Without sentence context the score favours short phrases ("five" over "fifteen"): no witness
            # is more honest than a biased one.
            continue
        runs = [scorer.score_slot(log_probs, slot, forms, ctx) for ctx in contexts]
        best = max(runs, key=lambda r: max(r.loglik.values()))
        scores.append(
            best.model_copy(
                update={
                    "loglik": {k: max(r.loglik[k] for r in runs) for k in forms},
                    "latency_ms": sum(r.latency_ms for r in runs),
                }
            )
        )
    return scores


def assemble(
    audio_sha: str,
    proposed: Values,
    hypotheses: list[Hypothesis],
    absent: list[str],
    scorer: Scorer | None = None,
    log_probs: np.ndarray | None = None,
    witness_latency_ms: float = 0.0,
) -> Evidence:
    """`hypotheses` are the in-time recogniser outputs, untyped. The witness is skipped when log_probs is None."""
    hyps = [typed(h) for h in hypotheses]
    witness: list[WitnessScore] = []
    absent = list(absent)
    if scorer is not None and log_probs is not None:
        free = typed(
            Hypothesis(
                source=GREEDY_SOURCE,
                family="ai4bharat",
                text=scorer.greedy(log_probs),
                latency_ms=witness_latency_ms,
            )
        )
        witness = witness_scores(scorer, log_probs, proposed, hyps, free)
        hyps.append(acoustic_vote(free, witness))
    else:
        absent.append(GREEDY_SOURCE)
    return Evidence(
        audio_sha=audio_sha,
        proposed=proposed,
        hypotheses=tuple(hyps),
        witness=tuple(witness),
        absent_sources=tuple(absent),
    )
