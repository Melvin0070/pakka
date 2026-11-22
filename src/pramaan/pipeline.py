"""The seam between the live shell and the evidence machinery.

The live server only knows `Guard`. `Pipeline` (below, real) and test fakes both satisfy it.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field

from . import audio, lang
from .bundle import BundleStore, make_bundle
from .decide import decide, resolve_answer
from .evidence import GREEDY_SOURCE, assemble
from .sources.base import Source
from .sources.registry import available_sources
from .types import Asked, Decision, Evidence, Hypothesis, Policy, Values
from .witness import Witness


class SourceTiming(BaseModel):
    source: str
    family: str
    latency_ms: float  # from end of caller turn
    in_time: bool
    heard: str = ""  # transcript, for the evidence table
    values: Values = Field(default_factory=dict)
    confidence: str = ""  # display string: a probability, an odds ratio, or "not exposed"


class Judgement(BaseModel):
    turn_id: str
    evidence: Evidence
    decision: Decision
    timings: list[SourceTiming]
    decided_after_ms: float  # tool call -> decision
    bundle_id: str = ""


class Guard(Protocol):
    async def start_turn(self, turn_id: str, pcm24k: bytes) -> None:
        """Called at end of caller speech, before any tool call: start the speculative evidence fan-out."""
        ...

    async def judge(
        self, turn_id: str, proposed: Values, confirming: bool = False, asked: Asked | None = None
    ) -> Judgement:
        """Called when the agent proposes a tool call for that turn. Waits at most the policy deadline."""
        ...

    async def cancel(self, turn_id: str) -> None:
        """Barge-in or cancelled response: drop in-flight work for the turn."""
        ...


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "data" / "policy.json"


def load_policy(path: Path = POLICY_PATH) -> Policy:
    return Policy(**json.loads(path.read_text())) if path.exists() else Policy()


@dataclass
class _Turn:
    sha: str
    started: float
    tasks: dict[str, asyncio.Task[Hypothesis | None]]
    witness: asyncio.Task[tuple[np.ndarray, float]]
    arrived: dict[str, float] = field(default_factory=dict)


class Pipeline:
    """Speculative fan-out at end of turn, deadline quorum at the tool call, pure decide()."""

    def __init__(
        self,
        policy: Policy | None = None,
        sources: list[Source] | None = None,
        witness: Witness | None = None,
        bundles: BundleStore | None = None,
    ) -> None:
        self.policy = policy or load_policy()
        self.sources = available_sources() if sources is None else sources
        self.witness = witness or Witness()
        self.bundles = bundles or BundleStore(lang.state_dir() / "bundles.jsonl")
        self._turns: dict[str, _Turn] = {}

    def warm(self) -> None:
        self.witness.log_probs(np.zeros(16000, dtype=np.int16), 16000)

    def _acoustic(self, pcm24k: bytes) -> tuple[np.ndarray, float]:
        t0 = time.perf_counter()
        lp = self.witness.log_probs(np.frombuffer(pcm24k, dtype=np.int16), audio.RATE)
        return lp, (time.perf_counter() - t0) * 1000

    async def start_turn(self, turn_id: str, pcm24k: bytes) -> None:
        sha = audio.sha(pcm24k)
        started = time.perf_counter()
        turn = _Turn(
            sha=sha,
            started=started,
            tasks={},
            witness=asyncio.create_task(asyncio.to_thread(self._acoustic, pcm24k)),
        )

        async def run(s: Source) -> Hypothesis | None:
            h = await s.hypothesis(pcm24k, sha)
            # A cache hit returns at once; wait out the recorded latency so a replayed clip meets the
            # deadline exactly as the original call did.
            if h is not None:
                await asyncio.sleep(max(0.0, h.latency_ms / 1000 - (time.perf_counter() - started)))
            turn.arrived[s.name] = (time.perf_counter() - started) * 1000
            return h

        turn.tasks = {s.name: asyncio.create_task(run(s)) for s in self.sources}
        self._turns[turn_id] = turn

    async def judge(
        self, turn_id: str, proposed: Values, confirming: bool = False, asked: Asked | None = None
    ) -> Judgement:
        turn = self._turns[turn_id]
        asked_at = time.perf_counter()
        pending = [*turn.tasks.values(), turn.witness]
        await asyncio.wait(pending, timeout=self.policy.deadline_ms / 1000)

        hyps: list[Hypothesis] = []
        absent: list[str] = []
        for name, task in turn.tasks.items():
            h = task.result() if task.done() and not task.cancelled() and task.exception() is None else None
            (hyps.append(h) if h is not None else absent.append(name))
        log_probs, witness_ms = (None, 0.0)
        if turn.witness.done() and turn.witness.exception() is None:
            log_probs, witness_ms = turn.witness.result()

        evidence = await asyncio.to_thread(
            assemble, turn.sha, proposed, hyps, absent, self.witness, log_probs, witness_ms
        )
        # An answer to a question is a second utterance of one value. The acoustic veto and the score threshold
        # exist to catch an error the transcribers share on a single utterance; on the answer the rule is that
        # independent families must agree on what was said, and the acoustic model votes but cannot veto.
        policy = self.policy
        if confirming:
            policy = policy.model_copy(update={"require_witness": False, "accept_threshold": 0.0})
            if asked is not None and asked.slot in proposed:
                evidence = resolve_answer(evidence, policy, asked)
        decision = decide(evidence, policy)
        decided_ms = (time.perf_counter() - asked_at) * 1000
        bundle = self.bundles.append(make_bundle(turn_id, evidence, decision))
        return Judgement(
            turn_id=turn_id,
            evidence=evidence,
            decision=decision,
            timings=self._timings(turn, evidence, witness_ms),
            decided_after_ms=decided_ms,
            bundle_id=bundle.id,
        )

    def _timings(self, turn: _Turn, evidence: Evidence, witness_ms: float) -> list[SourceTiming]:
        out: list[SourceTiming] = []
        heard = {h.source: h for h in evidence.hypotheses}
        for s in self.sources:
            h = heard.get(s.name)
            conf = "not exposed"
            if h and h.value_min_logprob:
                conf = f"{math.exp(min(h.value_min_logprob.values())):.2f}"
            out.append(
                SourceTiming(
                    source=s.name,
                    family=s.family,
                    latency_ms=turn.arrived.get(s.name, 0.0),
                    in_time=h is not None,
                    heard=h.text if h else "",
                    values=h.values if h else {},
                    confidence=conf if h else "",
                )
            )
        g = heard.get(GREEDY_SOURCE)
        odds = ""
        for w in evidence.witness:
            ranked = sorted(w.loglik.items(), key=lambda kv: -kv[1])
            if len(ranked) > 1:
                odds = f"{ranked[0][0]} over {ranked[1][0]}: {min(math.exp(ranked[0][1] - ranked[1][1]), 1e6):,.0f} to 1"
                break
        out.append(
            SourceTiming(
                source=f"{lang.get(self.witness.lang).name} acoustic model",
                family="ai4bharat",
                latency_ms=witness_ms,
                in_time=g is not None,
                heard=g.text if g else "",
                values=g.values if g else {},
                confidence=odds or ("scored" if evidence.witness else ""),
            )
        )
        return out

    async def cancel(self, turn_id: str) -> None:
        turn = self._turns.pop(turn_id, None)
        if turn:
            for t in turn.tasks.values():
                t.cancel()
