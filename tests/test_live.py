"""The live state machine driven by scripted Realtime events and a scripted guard. No network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from pramaan.live.fake_guard import FakeGuard
from pramaan.live.ledger import MemoryLedger, SqlLedger
from pramaan.live.ring import BYTES_PER_MS, RingBuffer, audio_sha
from pramaan.live.session import LEAD_IN_MS, MAX_QUESTIONS, CallSession
from pramaan.live.tooling import clean_args
from pramaan.types import Values

pytestmark = pytest.mark.anyio  # anyio's pytest plugin is already installed; no extra dependency


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


ARGS = {"amount_rupees": 2750, "day_of_month": None, "weekday": "tuesday", "phone": None}


class FakeLink:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, event: dict[str, Any]) -> None:
        self.sent.append(event)

    def outputs(self) -> list[dict[str, Any]]:
        return [
            json.loads(e["item"]["output"])
            for e in self.sent
            if e["type"] == "conversation.item.create" and e["item"]["type"] == "function_call_output"
        ]


class Rig:
    def __init__(
        self, ledger_cls: type = SqlLedger, script: tuple[str, ...] = ("ask", "pass"), delay_s: float = 0.0
    ) -> None:
        self.executed: list[Values] = []
        self.guard = FakeGuard(script=script, delay_s=delay_s)
        self.ledger = ledger_cls(self._tool)
        self.right, self.left = FakeLink(), FakeLink()
        self.events: list[dict[str, Any]] = []
        self.session = CallSession("sess01", self.guard, self.ledger, self.right, self.left, self._emit)
        self._n = 0

    def _tool(self, values: Values) -> dict[str, Any]:
        self.executed.append(values)
        return {"ok": True, "row": len(self.executed)}

    async def _emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [e["type"] for e in self.events]

    def last(self, kind: str) -> dict[str, Any]:
        return next(e for e in reversed(self.events) if e["type"] == kind)

    async def say(self, ms: int = 1000) -> None:
        start = self.session.ring.total_ms
        await self.session.on_right({"type": "input_audio_buffer.speech_started", "audio_start_ms": start})
        await self.session.caller_audio(bytes([self._n % 251 + 1]) * (ms * BYTES_PER_MS))
        await self.session.on_right({"type": "input_audio_buffer.speech_stopped", "audio_end_ms": start + ms})

    async def tool_call(
        self, args: dict[str, Any] | None = None, status: str = "completed", wait: bool = True
    ) -> str:
        self._n += 1
        call_id, rid = f"call_{self._n}", f"resp_{self._n}"
        await self.session.on_right({"type": "response.created", "response": {"id": rid}})
        item = {
            "type": "function_call",
            "name": "log_commitment",
            "call_id": call_id,
            "arguments": json.dumps(args or ARGS),
        }
        await self.session.on_right(
            {"type": "response.done", "response": {"id": rid, "status": status, "output": [item]}}
        )
        if wait:
            await self.session.idle()
        return call_id


def test_ring_slices_on_the_sample_clock() -> None:
    ring = RingBuffer(seconds=1.0)
    ring.append(b"\x01\x00" * 24000)  # 1 s
    assert ring.total_ms == 1000
    assert len(ring.slice_ms(100, 350)) == 250 * BYTES_PER_MS
    ring.append(b"\x02\x00" * 12000)  # +0.5 s: the first 0.5 s falls off
    assert ring.total_ms == 1500
    assert ring.slice_ms(0, 400) == b""
    assert ring.slice_ms(400, 600) == b"\x01\x00" * 2400
    assert ring.slice_ms(1400, 9999) == b"\x02\x00" * 2400
    assert ring.slice_ms(-300, 600) == b"\x01\x00" * 2400


def test_clean_args_drops_nulls_and_keeps_malformed_phones() -> None:
    assert clean_args(json.dumps(ARGS)) == {"amount_rupees": 2750, "weekday": "tuesday"}
    assert clean_args({"phone": "+91 98447 12000"}) == {"phone": "9844712000"}
    assert clean_args({"phone": "984471200"}) == {"phone": "984471200"}
    assert clean_args("not json") == {}


async def test_turn_is_sliced_with_lead_in_and_sent_to_guard_before_any_tool_call() -> None:
    rig = Rig()
    await rig.session.caller_audio(b"\x00\x00" * 24000)  # 1 s of room tone before speech
    await rig.say(800)
    await asyncio.sleep(0)
    ended = rig.last("turn.ended")
    assert ended["duration_ms"] == 800 + LEAD_IN_MS
    assert rig.guard._audio[ended["turn_id"]] == ended["audio_sha"]
    assert ended["audio_sha"] == audio_sha(rig.session.ring.slice_ms(1000 - LEAD_IN_MS, 1800))
    assert all(
        e["type"] == "input_audio_buffer.append" for e in rig.left.sent
    )  # the bare agent hears the same audio
    assert len(rig.left.sent) == 2


@pytest.mark.parametrize("ledger_cls", [SqlLedger, MemoryLedger])
async def test_hold_ask_answer_commit(ledger_cls: type) -> None:
    rig = Rig(ledger_cls)
    await rig.say()
    await rig.tool_call()
    assert rig.executed == []
    held = rig.right.outputs()[-1]
    assert held["status"] == "held" and held["ask_exactly"] == rig.last("question.asked")["text"]
    assert rig.right.sent[-1] == {"type": "response.create"}
    assert rig.session.awaiting_answer

    await rig.say()  # the caller answers
    await rig.tool_call()
    assert rig.executed == [{"amount_rupees": 2750, "weekday": "tuesday"}]
    assert rig.right.outputs()[-1]["status"] == "committed"
    committed = rig.last("right.committed")
    assert committed["questions"] == 1 and committed["executed"] is True
    # The weekday passed on the first turn, so only the amount is judged against the answer turn.
    assert [s["slot"] for s in rig.last("decision")["slots"]] == ["amount_rupees"]
    states = [t["state"] for t in rig.last("ledger")["transitions"]]
    assert states == ["proposed", "held", "asked", "proposed", "held", "committed"]


async def test_pass_commits_at_once() -> None:
    rig = Rig(script=("pass",))
    await rig.say()
    await rig.tool_call()
    assert len(rig.executed) == 1
    assert "question.asked" not in rig.kinds()


async def test_incomplete_response_never_executes() -> None:
    rig = Rig(script=("pass",))
    await rig.say()
    await rig.tool_call(status="cancelled")
    await rig.tool_call(status="incomplete")
    assert rig.executed == [] and rig.right.outputs() == []
    assert rig.last("right.voided")["reason"] == "response_incomplete"


@pytest.mark.parametrize("ledger_cls", [SqlLedger, MemoryLedger])
async def test_regenerated_and_duplicate_tool_calls_execute_once(ledger_cls: type) -> None:
    rig = Rig(ledger_cls, script=("pass",))
    await rig.say()
    await rig.tool_call()
    for _ in range(3):  # new call ids and response ids, same business operation
        await rig.tool_call()
    assert len(rig.executed) == 1
    assert rig.kinds().count("right.duplicate") == 3
    assert rig.right.outputs()[-1] == {"status": "committed", "note": "already recorded"}


async def test_correction_after_commit_is_a_new_version_and_is_judged_again() -> None:
    rig = Rig(script=("pass",))
    await rig.say()
    await rig.tool_call()
    await rig.say()
    await rig.tool_call({**ARGS, "amount_rupees": 3750})
    assert [v["amount_rupees"] for v in rig.executed] == [2750, 3750]
    assert rig.last("right.proposed")["entity_version"] == 2


@pytest.mark.parametrize("ledger_cls", [SqlLedger, MemoryLedger])
async def test_barge_in_while_held_voids_the_action(ledger_cls: type) -> None:
    rig = Rig(ledger_cls, script=("pass",), delay_s=5.0)
    await rig.say()
    call_id = await rig.tool_call(wait=False)
    await asyncio.sleep(0.01)  # the judge is now in flight
    assert rig.last("ledger")["state"] == "held"
    await rig.session.on_right(
        {"type": "input_audio_buffer.speech_started", "audio_start_ms": rig.session.ring.total_ms}
    )
    assert rig.executed == []
    assert rig.guard.cancelled == ["sess01-t1"]
    assert rig.last("right.voided")["reason"] == "caller_spoke_again"
    assert rig.last("ledger")["state"] == "voided"
    voided = [e for e in rig.right.sent if e["type"] == "conversation.item.create"][-1]["item"]
    assert voided["call_id"] == call_id and json.loads(voided["output"])["status"] == "voided"
    assert (
        rig.right.sent[-1]["type"] != "response.create"
    )  # the caller is talking: the model must not answer yet

    # What the caller says next is judged as a fresh version and can still commit, once.
    rig.guard.delay_s = 0.0
    await rig.session.caller_audio(b"\x01\x00" * 24000)
    await rig.session.on_right(
        {"type": "input_audio_buffer.speech_stopped", "audio_end_ms": rig.session.ring.total_ms}
    )
    await rig.tool_call()
    assert len(rig.executed) == 1 and rig.last("right.proposed")["entity_version"] == 2


async def test_barge_in_during_agent_speech_flushes_and_cancels() -> None:
    rig = Rig()
    await rig.say()
    await rig.session.on_right({"type": "response.created", "response": {"id": "resp_x"}})
    await rig.session.on_right({"type": "response.output_audio.delta", "delta": "AAAA"})
    await rig.session.on_right({"type": "input_audio_buffer.speech_started", "audio_start_ms": 2000})
    assert "agent.flush" in rig.kinds()
    assert {"type": "response.cancel"} in rig.right.sent


async def test_escalates_after_the_question_cap() -> None:
    rig = Rig(script=("ask",))
    for _ in range(MAX_QUESTIONS + 1):
        await rig.say()
        await rig.tool_call()
    assert rig.executed == []
    assert rig.kinds().count("question.asked") == MAX_QUESTIONS
    assert rig.right.outputs()[-1] == {"status": "escalated"}
    assert rig.last("ledger")["state"] == "voided"


async def test_block_asks_the_caller_to_repeat() -> None:
    rig = Rig(script=("block", "pass"))
    await rig.say()
    await rig.tool_call()
    asked = rig.last("question.asked")
    assert asked["ask_kind"] == "block" and "dobara" in asked["text"]
    assert rig.executed == []


async def test_left_agent_commits_immediately_and_is_only_reported() -> None:
    rig = Rig()
    await rig.say()
    await rig.session.on_left({"type": "input_audio_buffer.speech_stopped"})
    item = {"type": "function_call", "name": "log_commitment", "call_id": "L1", "arguments": json.dumps(ARGS)}
    await rig.session.on_left(
        {"type": "response.done", "response": {"status": "completed", "output": [item]}}
    )
    assert rig.last("left.committed")["values"] == {"amount_rupees": 2750, "weekday": "tuesday"}
    assert rig.executed == []  # the bare agent has no route to the real tool


async def test_every_event_carries_a_turn_id_field() -> None:
    rig = Rig()
    await rig.say()
    await rig.tool_call()
    assert all("turn_id" in e and "t_ms" in e for e in rig.events)
    assert all(
        e["turn_id"] == "sess01-t1"
        for e in rig.events
        if e["type"] in ("right.held", "decision", "evidence", "question.asked")
    )


async def test_value_split_across_vad_turns_is_judged_on_the_whole_span() -> None:
    rig = Rig(script=("pass",))
    await rig.session.caller_audio(b"\x00\x00" * 24000)
    await rig.say(600)
    await rig.say(900)  # no tool call in between: the same utterance, split by a pause
    ended = rig.last("turn.ended")
    assert ended["merged_turns"] == 2 and ended["duration_ms"] == 1500 + LEAD_IN_MS
    assert rig.guard.cancelled == ["sess01-t1"]
    await rig.tool_call()
    await rig.say(500)
    assert rig.last("turn.ended")["merged_turns"] == 1  # a proposal closes the span


async def test_guard_failure_never_executes() -> None:
    rig = Rig(script=("pass",))

    async def boom(turn_id: str, proposed: Values) -> Any:
        raise RuntimeError("source pool down")

    rig.guard.judge = boom  # type: ignore[method-assign]
    await rig.say()
    await rig.tool_call()
    assert rig.executed == []
    assert rig.last("error")["side"] == "guard"
    assert rig.right.outputs()[-1]["status"] == "held"


async def test_questioned_value_dropped_by_the_agent_is_not_committed() -> None:
    rig = Rig(MemoryLedger)
    await rig.say()
    await rig.tool_call()  # the guard questions the amount
    await rig.say()
    await rig.tool_call({"weekday": "tuesday"})  # the agent comes back without it
    assert rig.executed == []
    asked = rig.last("question.asked")
    assert asked["slot"] == "amount_rupees" and asked["n"] == 2
    await rig.say()
    await rig.tool_call()
    assert rig.executed == [{"amount_rupees": 2750, "weekday": "tuesday"}]


async def test_value_that_passed_survives_a_later_tool_call_that_drops_it() -> None:
    rig = Rig(MemoryLedger)
    await rig.say()
    await rig.tool_call()  # weekday passes, amount is questioned
    await rig.say()
    await rig.tool_call({"amount_rupees": 2750})  # the agent answers with the amount only
    assert rig.executed == [{"amount_rupees": 2750, "weekday": "tuesday"}]
