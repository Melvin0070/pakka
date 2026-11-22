"""One call: a Realtime agent's tool calls held until judged, beside the same call left unguarded.

By default the left pane is the guarded agent's own first tool call, executed as it stood. A second,
independent agent can be attached instead (`left`), which the offline replay and scripts/fresh_mic.py use.

No network here. The server feeds Realtime events in and passes a `Link` for sending; tests do the same with fakes.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .. import lang
from .. import question as questions
from ..pipeline import Guard
from ..types import Asked, Values, Verdict
from .ledger import Entry, Ledger
from .ring import RATE, RingBuffer, audio_sha
from .tooling import TOOL_NAME, clean_args

log = logging.getLogger("pramaan.live")

LEAD_IN_MS = 300
MAX_QUESTIONS = 2
MAX_SPAN_MS = 30_000
SLOT_LABEL = {
    "amount_rupees": "amount",
    "day_of_month": "tareekh",
    "weekday": "din",
    "phone": "phone number",
    "pincode": "PIN code",
    "account_number": "account number",
}

Emit = Callable[[dict[str, Any]], Awaitable[None]]


class Link(Protocol):
    async def send(self, event: dict[str, Any]) -> None: ...


@dataclass
class Turn:
    id: str
    start_ms: float
    end_ms: float | None = None
    stopped_at: float | None = None  # clock time of speech_stopped
    started: asyncio.Task[None] | None = None  # guard.start_turn in flight


@dataclass
class Action:
    """One business operation as it moves through proposals, questions and a commit."""

    version: int
    entry: Entry | None = None
    settled: Values = field(default_factory=dict)  # slots that already passed the guard
    passed: Values = field(
        default_factory=dict
    )  # the value to execute for each slot that passed, repairs applied
    doubted: set[str] = field(default_factory=set)  # slots the guard questioned and has not passed since
    questions: int = 0
    asked: Asked | None = None  # the forced choice awaiting an answer
    first_proposed_at: float | None = None
    committed: Values | None = None
    closed: bool = False


class CallSession:
    def __init__(
        self,
        session_id: str,
        guard: Guard,
        ledger: Ledger,
        right: Link,
        left: Link | None,
        emit: Emit,
        clock: Callable[[], float] = time.monotonic,
        mirror_left: bool = False,
    ) -> None:
        self.id = session_id
        self.guard, self.ledger, self.right, self.left, self._emit = guard, ledger, right, left, emit
        self.clock = clock
        self.t0 = clock()
        # The business operation, not a call or response id: a regenerated tool call maps to the same row.
        self.operation = f"{TOOL_NAME}:{session_id}"
        self.ring = RingBuffer()
        self.turns: list[Turn] = []
        self.action = Action(version=1)
        self.awaiting_answer = False
        self.question_spoken = False  # the agent has finished saying the pending question
        self.final = False  # committed or escalated: replay mode may stop
        self.closing_spoken = False  # the agent has spoken after the final outcome
        self.agent_quiet_at = 0.0  # clock time by which the agent's audio has finished playing
        self._open_turn: Turn | None = None
        self._span: list[
            Turn
        ] = []  # caller turns since the last proposal: one value can straddle a VAD split
        self._judging: tuple[asyncio.Task[None], Turn, str] | None = None
        self._answered: str | None = None  # call id whose proposal has reached its outcome
        self._active_response: str | None = None
        self._audio_started: float | None = None
        self._audio_bytes = 0
        self._left_stopped_at: float | None = None
        self._left_turn: str = ""
        self.mirror_left = mirror_left
        self._left_mirrored = False

    # ---- plumbing

    async def emit(self, kind: str, turn_id: str = "", **fields: Any) -> None:
        event = {"type": kind, "turn_id": turn_id, "t_ms": round((self.clock() - self.t0) * 1000), **fields}
        if kind not in ("agent.audio", "caller.audio"):
            log.info(json.dumps({"session": self.id, **event}, ensure_ascii=False, default=str))
        await self._emit(event)

    async def caller_audio(self, pcm: bytes) -> None:
        self.ring.append(pcm)
        event = {"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()}
        await self.right.send(event)
        if self.left:
            await self.left.send(event)

    async def idle(self) -> None:
        """Wait for in-flight judging to finish (tests and shutdown)."""
        while self._judging and not self._judging[0].done():
            with contextlib.suppress(asyncio.CancelledError):
                await self._judging[0]

    async def close(self) -> None:
        if self._judging and not self._judging[0].done():
            self._judging[0].cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._judging[0]
        # Recogniser calls for turns nobody will judge would otherwise run on, and keep their audio.
        for turn in self.turns:
            if turn.started is not None:
                turn.started.cancel()
            with contextlib.suppress(Exception):
                await self.guard.cancel(turn.id)

    async def _tool_output(self, call_id: str, output: dict[str, Any], respond: bool) -> None:
        await self.right.send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output, ensure_ascii=False),
                },
            }
        )
        if respond:
            await self.right.send({"type": "response.create"})

    async def _ledger_event(self, entry: Entry, turn_id: str) -> None:
        await self.emit(
            "ledger",
            turn_id,
            entry_id=entry.id,
            state=entry.state.value,
            entity_version=entry.entity_version,
            transitions=[{"state": s, "at": t, "note": n} for s, t, n in entry.transitions],
        )

    def _report(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            log.error(
                json.dumps({"session": self.id, "type": "proposal.crashed", "error": repr(task.exception())})
            )

    # ---- right agent (guarded)

    async def on_right(self, ev: dict[str, Any]) -> None:
        kind = ev.get("type", "")
        if kind == "input_audio_buffer.speech_started":
            await self._speech_started(ev)
        elif kind == "input_audio_buffer.speech_stopped":
            await self._speech_stopped(ev)
        elif kind == "response.created":
            self._active_response = ev["response"]["id"]
            self._audio_started, self._audio_bytes = None, 0
        elif kind == "response.output_audio.delta":
            if self._audio_started is None:
                self._audio_started = self.clock()
            self._audio_bytes += len(ev["delta"]) * 3 // 4
            await self.emit("agent.audio", self._turn_id(), audio=ev["delta"])
        elif kind == "response.output_audio_transcript.done":
            await self.emit("agent.said", self._turn_id(), text=ev.get("transcript", ""))
        elif kind == "response.done":
            await self._response_done(ev["response"])
        elif kind == "error":
            err = ev.get("error", {})
            # Cancelling when the server already stopped the response is expected on barge-in.
            if err.get("code") != "response_cancel_not_active":
                await self.emit("error", self._turn_id(), side="right", message=err.get("message", str(err)))

    def _turn_id(self) -> str:
        return self.turns[-1].id if self.turns else ""

    async def _speech_started(self, ev: dict[str, Any]) -> None:
        turn = Turn(
            id=f"{self.id}-t{len(self.turns) + 1}",
            start_ms=float(ev.get("audio_start_ms", self.ring.total_ms)),
        )
        self.turns.append(turn)
        self._open_turn = turn
        await self.emit("turn.started", turn.id, audio_start_ms=turn.start_ms)
        if self._active_response or self.clock() < self.agent_quiet_at:
            await self.emit("agent.flush", turn.id)
            if self._active_response:
                await self.right.send({"type": "response.cancel"})
            self.agent_quiet_at = self.clock()
        # Once a proposal has committed or been put to the caller, only its reply to the model is left:
        # cancelling there would tell the model "voided" about an action that already ran, and it would
        # run again on the model's retry.
        if self._judging and not self._judging[0].done() and self._judging[2] != self._answered:
            # The caller spoke again while an action was held and unjudged: what they say may correct it.
            task, held_turn, call_id = self._judging
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await self.guard.cancel(held_turn.id)
            await self._void(held_turn.id, "caller_spoke_again")
            await self._tool_output(
                call_id, {"status": "voided", "reason": "caller spoke again"}, respond=False
            )

    async def _speech_stopped(self, ev: dict[str, Any]) -> None:
        turn = self._open_turn
        if turn is None:
            return
        self._open_turn = None
        turn.end_ms = float(ev.get("audio_end_ms", self.ring.total_ms))
        turn.stopped_at = self.clock()
        for earlier in self._span:
            await self.guard.cancel(earlier.id)
        self._span.append(turn)
        span_start = max(self._span[0].start_ms, turn.end_ms - MAX_SPAN_MS)
        pcm = self.ring.slice_ms(span_start - LEAD_IN_MS, turn.end_ms)
        # Speculative: evidence gathering starts here, before the agent has proposed anything.
        turn.started = asyncio.create_task(self.guard.start_turn(turn.id, pcm))
        await self.emit(
            "turn.ended",
            turn.id,
            audio_start_ms=span_start,
            audio_end_ms=turn.end_ms,
            merged_turns=len(self._span),
            duration_ms=round(len(pcm) * 1000 / (RATE * 2)),
            audio_sha=audio_sha(pcm),
        )

    async def _response_done(self, response: dict[str, Any]) -> None:
        self._active_response = None
        if self._audio_started is not None:
            self.agent_quiet_at = max(self.clock(), self._audio_started + self._audio_bytes / (RATE * 2))
            if self.awaiting_answer and response.get("status") == "completed":
                self.question_spoken = True
            if self.final:
                self.closing_spoken = True
        calls = [
            o
            for o in response.get("output", [])
            if o.get("type") == "function_call" and o.get("name") == TOOL_NAME
        ]
        status = response.get("status")
        turn = next((t for t in reversed(self.turns) if t.stopped_at is not None), None)
        proposals: list[tuple[str, Values]] = []
        for call in calls:
            if status != "completed":
                # arguments.done also fires on cancelled responses; nothing from them may execute.
                await self.emit(
                    "right.voided",
                    turn.id if turn else "",
                    reason=f"response_{status}",
                    call_id=call.get("call_id"),
                )
                continue
            if turn is None:
                await self._tool_output(
                    call["call_id"], {"status": "voided", "reason": "no caller turn"}, respond=False
                )
                continue
            proposals.append((call["call_id"], clean_args(call.get("arguments", "{}"))))
        if proposals and turn is not None:
            self._span = []
            task = asyncio.create_task(self._proposals(turn, proposals))
            task.add_done_callback(self._report)
            self._judging = (task, turn, proposals[0][0])

    async def _proposals(self, turn: Turn, proposals: list[tuple[str, Values]]) -> None:
        """One at a time: calls from one response share a ledger row, so judged together one would be lost."""
        task = asyncio.current_task()
        assert task is not None
        for call_id, values in proposals:
            self._judging = (task, turn, call_id)
            try:
                await self._proposal(turn, call_id, values)
            except Exception as e:  # noqa: BLE001 - the model must get an answer, and nothing may run
                if self._answered == call_id:
                    raise
                await self.emit("error", turn.id, side="guard", message=f"{type(e).__name__}: {e}")
                await self._void(turn.id, "guard_error")
                await self._tool_output(call_id, {"status": "voided", "reason": "internal error"}, True)

    async def _void(self, turn_id: str, reason: str) -> None:
        entry = self.action.entry
        if entry is not None:
            self.ledger.void(entry, reason)
            await self._ledger_event(entry, turn_id)
        await self.emit("right.voided", turn_id, reason=reason)
        # A void means the value may have changed: the next proposal is a new version of the entity.
        self._new_version()
        self.awaiting_answer = False

    def _new_version(self) -> None:
        self.action = Action(version=self.ledger.correct(self.id, self.operation))

    async def _proposal(self, turn: Turn, call_id: str, values: Values) -> None:
        now = self.clock()
        action = self.action
        if action.committed is not None:
            if values == action.committed:
                # A regenerated call for something already done: answer from the ledger, execute nothing.
                self._answered = call_id
                await self.emit("right.duplicate", turn.id, values=values)
                await self._tool_output(
                    call_id, {"status": "committed", "note": "already recorded"}, respond=True
                )
                return
            self._new_version()
            action = self.action
        if action.first_proposed_at is None:
            action.first_proposed_at = turn.stopped_at or now
        entry = action.entry = self.ledger.propose(self.id, self.operation, values)
        self.awaiting_answer = False
        await self.emit(
            "right.proposed",
            turn.id,
            values=values,
            latency_ms=round((now - (turn.stopped_at or now)) * 1000),
            entity_version=action.version,
            call_id=call_id,
        )
        if self.mirror_left and not self._left_mirrored:
            # Two sessions sample two different mishearings; the fair "without" is this same call, unguarded.
            self._left_mirrored = True
            await self.emit(
                "left.committed",
                turn.id,
                values=values,
                latency_ms=round((now - (turn.stopped_at or now)) * 1000),
            )
        self.ledger.hold(entry)
        await self._ledger_event(entry, turn.id)
        await self.emit("right.held", turn.id, entry_id=entry.id)

        to_judge = {k: v for k, v in values.items() if action.settled.get(k) != v}
        # A value the guard questioned must come back and pass; the agent leaving it out is not a resolution.
        dropped = sorted(action.doubted - values.keys())
        if dropped:
            verdict, decision = Verdict.BLOCK, None
        elif to_judge:
            if turn.started is not None:
                await turn.started
            judged_at = self.clock()
            try:
                j = await self.guard.judge(
                    turn.id, to_judge, confirming=action.questions > 0, asked=action.asked
                )
            except Exception as e:  # noqa: BLE001 - a guard failure must never become an execution
                await self.emit(
                    "error", turn.id, side="guard", message=f"evidence check failed: {type(e).__name__}: {e}"
                )
                j = None
            if j is None:
                verdict, decision = Verdict.BLOCK, None
            else:
                await self.emit(
                    "evidence",
                    turn.id,
                    timings=[t.model_dump() for t in j.timings],
                    decided_after_ms=round(j.decided_after_ms),
                    waited_ms=round((self.clock() - judged_at) * 1000),
                    bundle_id=j.bundle_id,
                    policy_hash=j.decision.policy_hash,
                    absent_sources=list(j.evidence.absent_sources),
                    witness=[w.model_dump() for w in j.evidence.witness],
                )
                await self.emit(
                    "decision",
                    turn.id,
                    verdict=j.decision.verdict.value,
                    score=j.decision.score,
                    slots=[s.model_dump(mode="json") for s in j.decision.slots],
                    question=j.decision.question,
                    question_slot=j.decision.question_slot,
                    proposed=values,
                )
                for s in j.decision.slots:
                    won = s.final if s.final is not None else s.proposed
                    if s.verdict == Verdict.PASS and won is not None:
                        action.passed[s.slot] = won
                    if s.verdict == Verdict.PASS and s.proposed is not None:
                        action.settled[s.slot] = s.proposed
                        action.doubted.discard(s.slot)
                    elif s.proposed is not None:
                        action.doubted.add(s.slot)
                verdict, decision = j.decision.verdict, j.decision
        else:
            verdict, decision = Verdict.PASS, None

        if verdict == Verdict.PASS:
            proposed = dict(values)
            # Slots that passed on an earlier turn keep the value that passed, even if the agent has since
            # dropped them or repeats the value the evidence corrected.
            kept = {k: v for k, v in action.passed.items() if k not in to_judge}
            values = {**values, **kept, **(decision.execute if decision is not None else {})}
            if values != proposed:
                # The evidence supports a different value than the agent proposed: the ledger row takes the
                # repaired arguments, so the old confirmation token goes stale before anything runs.
                entry = action.entry = self.ledger.propose(self.id, self.operation, values)
                self.ledger.hold(entry)
            executed, outcome = self.ledger.commit(entry)
            self._answered = call_id
            action.committed, action.closed = dict(values), True
            self.final = True
            await self._ledger_event(entry, turn.id)
            await self.emit(
                "right.committed",
                turn.id,
                values=values,
                repaired_from=proposed if values != proposed else None,
                executed=executed,
                outcome=outcome,
                questions=action.questions,
                total_ms=round((self.clock() - (action.first_proposed_at or now)) * 1000),
            )
            await self._tool_output(call_id, {"status": "committed", **values}, respond=True)
            return

        if action.questions >= MAX_QUESTIONS:
            self.ledger.void(entry, "escalated")
            self._answered = call_id
            await self._ledger_event(entry, turn.id)
            await self.emit("right.escalated", turn.id, values=values, questions=action.questions)
            self._new_version()
            self.final = True
            await self._tool_output(call_id, {"status": "escalated"}, respond=True)
            return

        action.questions += 1
        doubt = next((s for s in (decision.slots if decision else ()) if s.verdict != Verdict.PASS), None)
        if decision is not None and decision.question_slot:
            doubt = next((s for s in decision.slots if s.slot == decision.question_slot), doubt)
        code = lang.get().code
        if code != "hi" and doubt is not None:
            # decide() phrases in Hinglish and stays pure; another language rephrases the same decision.
            question = questions.phrase(doubt, code)
        elif decision is not None and decision.question:
            question = decision.question
        else:
            label = SLOT_LABEL.get(dropped[0] if dropped else doubt.slot if doubt else "", "woh")
            question = f"Maaf kijiye, {label} ek baar dheere se dobara bataiye?"
        action.asked = None
        if decision is not None and doubt is not None and doubt.verdict == Verdict.ASK:
            options = doubt.candidates[: questions.MAX_SPOKEN_OPTIONS]
            action.asked = Asked(slot=doubt.slot, options=tuple(questions.option_order(options)))
        self.ledger.ask(entry, question)
        self._answered = call_id
        self.awaiting_answer, self.question_spoken = True, False
        await self._ledger_event(entry, turn.id)
        await self.emit(
            "question.asked",
            turn.id,
            text=question,
            n=action.questions,
            ask_kind=verdict.value,
            slot=dropped[0] if dropped else doubt.slot if doubt else None,
        )
        await self._tool_output(call_id, {"status": "held", "ask_exactly": question}, respond=True)

    # ---- left agent (bare): whatever it proposes executes at once

    async def on_left(self, ev: dict[str, Any]) -> None:
        kind = ev.get("type", "")
        if kind == "input_audio_buffer.speech_stopped":
            self._left_stopped_at = self.clock()
            self._left_turn = self._turn_id()
        elif kind == "response.done":
            response = ev["response"]
            for call in response.get("output", []):
                if call.get("type") != "function_call" or response.get("status") != "completed":
                    continue
                now = self.clock()
                await self.emit(
                    "left.committed",
                    self._left_turn or self._turn_id(),
                    values=clean_args(call.get("arguments", "{}")),
                    latency_ms=round((now - (self._left_stopped_at or now)) * 1000),
                )
                if self.left:
                    await self.left.send(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call["call_id"],
                                "output": '{"status":"committed"}',
                            },
                        }
                    )
        elif kind == "error":
            err = ev.get("error", {})
            await self.emit("error", self._turn_id(), side="left", message=err.get("message", str(err)))
