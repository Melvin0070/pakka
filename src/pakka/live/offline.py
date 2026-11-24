"""Replay a recorded call with no network: the Realtime model is replaced by its own recorded answer.

Used when PAKKA_OFFLINE=1 (venue network down). Both agents get the tool call gpt-realtime-2.1 made for
this exact clip during collection, after the response time recorded with it; live they are two independent
sessions and can differ. Every recogniser answers from data/cache.sqlite and the acoustic model runs locally,
so the evidence, the decision and the ledger are the real code paths. The agent's speech is text only.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .. import audio
from ..cache import CacheMiss
from ..pipeline import Guard, Judgement
from ..sources import realtime_agent
from ..types import Asked, Values
from .session import CallSession
from .tooling import TOOL_NAME

FRAME_MS = 100
FRAME_BYTES = audio.RATE * 2 * FRAME_MS // 1000
Handler = Callable[[dict[str, Any]], Awaitable[None]]


class ClipGuard:
    """Hands the guard the clip's own bytes instead of the session's re-cut span, so cache keys match."""

    def __init__(self, inner: Guard) -> None:
        self.inner = inner
        self.pcm = b""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def start_turn(self, turn_id: str, pcm24k: bytes) -> None:
        await self.inner.start_turn(turn_id, self.pcm or pcm24k)

    async def judge(
        self, turn_id: str, proposed: Values, confirming: bool = False, asked: Asked | None = None
    ) -> Judgement:
        return await self.inner.judge(turn_id, proposed, confirming, asked)

    async def cancel(self, turn_id: str) -> None:
        await self.inner.cancel(turn_id)


def _spoken(output: dict[str, Any]) -> str:
    status = output.get("status")
    if status == "held":
        return str(output.get("ask_exactly", ""))
    if status == "escalated":
        return "Hamare colleague aapko call karke details confirm karenge."
    if status == "committed":
        said = ", ".join(str(v) for k, v in output.items() if k not in ("status", "note"))
        return f"Note kar liya: {said}." if said else "Yeh pehle se note hai."
    return ""


class CachedAgent:
    """Stands where a Realtime socket would: takes the session's sends, answers with scripted events."""

    def __init__(self, speak: bool) -> None:
        self.speak = speak
        self.handler: Handler | None = None
        self._n = 0
        self._pending: dict[str, Any] | None = None

    async def _to_session(self, event: dict[str, Any]) -> None:
        if self.handler is not None:
            await self.handler(event)

    async def send(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "conversation.item.create" and event["item"].get("type") == "function_call_output":
            self._pending = json.loads(event["item"]["output"])
        elif kind == "response.create" and self.speak and self._pending is not None:
            text, self._pending = _spoken(self._pending), None
            self._n += 1
            rid = f"offline_resp_{self._n}"
            await self._to_session({"type": "response.created", "response": {"id": rid}})
            if text:
                await self._to_session({"type": "response.output_audio_transcript.done", "transcript": text})
            await self._to_session(
                {"type": "response.done", "response": {"id": rid, "status": "completed", "output": []}}
            )

    async def heard(self, kind: str, at_ms: float) -> None:
        key = "audio_start_ms" if kind == "speech_started" else "audio_end_ms"
        await self._to_session({"type": f"input_audio_buffer.{kind}", key: at_ms})

    async def tool_call(self, arguments: dict[str, Any]) -> None:
        self._n += 1
        rid, call = f"offline_resp_{self._n}", f"offline_call_{self._n}"
        await self._to_session({"type": "response.created", "response": {"id": rid}})
        output = [
            {
                "type": "function_call",
                "name": TOOL_NAME,
                "call_id": call,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            }
        ]
        await self._to_session(
            {"type": "response.done", "response": {"id": rid, "status": "completed", "output": output}}
        )


async def replay(
    session: CallSession, guard: ClipGuard, right: CachedAgent, left: CachedAgent | None, path: Path
) -> None:
    """One clip, in real time. A question ends the replay: there is no recorded answer to a question."""
    pcm = audio.read_pcm24k(path)
    try:
        proposal = await realtime_agent.propose(pcm, audio.sha(pcm))
    except CacheMiss:
        await session.emit(
            "error", message=f"{path.stem} was never collected, so it cannot be replayed offline"
        )
        await session.emit("replay.done", reason="not_cached")
        return
    guard.pcm = pcm
    agents = [a for a in (left, right) if a is not None]
    await session.emit("replay.clip", clip=path.stem, duration_ms=len(pcm) * 1000 // (audio.RATE * 2))
    start_ms = session.ring.total_ms
    for a in agents:
        await a.heard("speech_started", start_ms)
    next_frame = session.clock()
    for pos in range(0, len(pcm), FRAME_BYTES):
        frame = pcm[pos : pos + FRAME_BYTES]
        await session.emit("caller.audio", audio=base64.b64encode(frame).decode())
        await session.caller_audio(frame)
        next_frame += FRAME_MS / 1000
        await asyncio.sleep(max(next_frame - session.clock(), 0))
    for a in agents:
        await a.heard("speech_stopped", session.ring.total_ms)
    if proposal is None:
        await session.emit("error", message="the recorded model made no tool call for this clip")
    else:
        await asyncio.sleep((proposal.response_ms or 0.0) / 1000)
        for a in agents:
            await a.tool_call(proposal.raw)
        await session.idle()
        await asyncio.sleep(1.0)  # let the page show the outcome before the socket closes
    await session.emit("replay.done", reason="settled")
