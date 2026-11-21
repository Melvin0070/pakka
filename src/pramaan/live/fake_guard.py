"""A scripted Guard so the live path and UI run before the real pipeline exists. Evidence is invented."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from ..pipeline import Judgement, SourceTiming
from ..types import Decision, Evidence, Hypothesis, Policy, SlotDecision, Value, Values, Verdict
from .ring import audio_sha


def _alternative(slot: str, value: Value) -> Value:
    if slot == "amount_rupees":
        return int(value) + (1000 if int(value) >= 1000 else 100)
    if slot == "day_of_month":
        return int(value) % 31 + 1
    if slot == "weekday":
        return "friday" if value != "friday" else "monday"
    digits = str(value)
    i = max(len(digits) - 3, 0)
    return digits[:i] + ("1" if digits[i : i + 1] == "7" else "7") + digits[i + 1 :]


class FakeGuard:
    """Verdicts follow `script` per session (the turn_id prefix before '-t'), then repeat its last entry."""

    is_fake = True

    def __init__(self, script: tuple[str, ...] = ("ask", "pass"), delay_s: float = 0.4) -> None:
        self.script = script
        self.delay_s = delay_s
        self.policy = Policy(version="fake")
        self._calls: dict[str, int] = defaultdict(int)
        self._audio: dict[str, str] = {}
        self.cancelled: list[str] = []

    async def start_turn(self, turn_id: str, pcm24k: bytes) -> None:
        self._audio[turn_id] = audio_sha(pcm24k)

    async def cancel(self, turn_id: str) -> None:
        self.cancelled.append(turn_id)

    async def judge(self, turn_id: str, proposed: Values, confirming: bool = False) -> Judgement:
        session = turn_id.rsplit("-t", 1)[0]
        step = self.script[min(self._calls[session], len(self.script) - 1)]
        self._calls[session] += 1
        await asyncio.sleep(self.delay_s)
        verdict = Verdict(step)
        doubt = next(iter(proposed), None) if verdict != Verdict.PASS else None
        slots: list[SlotDecision] = []
        heard: Values = dict(proposed)
        for slot, value in proposed.items():
            if slot != doubt:
                slots.append(
                    SlotDecision(slot=slot, proposed=value, verdict=Verdict.PASS, reason="families_agree",  # type: ignore[arg-type]
                                 candidates=(value,), posterior={str(value): 0.97}, score=0.97,
                                 supporting_families=("openai-transcribe", "ai4bharat"), witness_llr=5.4)
                )  # fmt: skip
                continue
            alt = _alternative(slot, value)
            heard[slot] = alt
            a, b = str(value), str(alt)
            contested = (
                tuple(i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y)
                if len(a) == len(b)
                else ()
            )
            cands = (alt, value) if verdict == Verdict.ASK else (value,)
            slots.append(
                SlotDecision(slot=slot, proposed=value, verdict=verdict, reason="proposed_unsupported",  # type: ignore[arg-type]
                             candidates=cands, posterior={b: 0.9, a: 0.1}, score=0.1,
                             supporting_families=(), witness_llr=-5.4, contested_positions=contested)
            )  # fmt: skip
        question = f"{heard[doubt]} ya {proposed[doubt]}?" if doubt and verdict == Verdict.ASK else None
        decision = Decision(
            verdict=verdict, slots=tuple(slots), score=min((s.score for s in slots), default=0.0),
            question=question, question_slot=doubt if question else None, policy_hash=self.policy.hash,  # type: ignore[arg-type]
        )  # fmt: skip
        hyps = (
            Hypothesis(source="gpt-transcribe", family="openai-transcribe", text="(fake evidence)", latency_ms=610, values=heard),
            Hypothesis(source="gpt-4o-transcribe", family="openai-transcribe", text="(fake evidence)", latency_ms=720, values=heard),
        )  # fmt: skip
        evidence = Evidence(
            audio_sha=self._audio.get(turn_id, ""),
            proposed=proposed,
            hypotheses=hyps,
            absent_sources=("saaras",),
        )
        timings = [
            SourceTiming(source="indicconformer-hi", family="ai4bharat", latency_ms=240, in_time=True, heard="(fake evidence)", values=heard, confidence="212 to 1"),
            SourceTiming(source="gpt-transcribe", family="openai-transcribe", latency_ms=610, in_time=True, heard="(fake evidence)", values=heard, confidence="not exposed"),
            SourceTiming(source="gpt-4o-transcribe", family="openai-transcribe", latency_ms=720, in_time=True, heard="(fake evidence)", values=heard, confidence="0.91"),
            SourceTiming(source="saaras", family="sarvam", latency_ms=1480, in_time=False),
        ]  # fmt: skip
        bundle = audio_sha(f"{turn_id}:{self._calls[session]}".encode())[:16]
        return Judgement(turn_id=turn_id, evidence=evidence, decision=decision, timings=timings,
                         decided_after_ms=self.delay_s * 1000, bundle_id=bundle)  # fmt: skip
