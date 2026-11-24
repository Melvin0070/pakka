"""Offline replay: the cached stand-in for the Realtime model drives the real session state machine."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from pakka import audio
from pakka.live import offline
from pakka.live.fake_guard import FakeGuard
from pakka.live.ledger import MemoryLedger
from pakka.live.session import CallSession
from pakka.sources import realtime_agent
from pakka.types import Values

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Rig:
    def __init__(self, script: tuple[str, ...]) -> None:
        self.executed: list[Values] = []
        self.events: list[dict[str, Any]] = []
        self.heard: list[bytes] = []
        inner = FakeGuard(script=script)
        start = inner.start_turn

        async def spy(turn_id: str, pcm: bytes) -> None:
            self.heard.append(pcm)
            await start(turn_id, pcm)

        inner.start_turn = spy  # type: ignore[method-assign]
        self.guard = offline.ClipGuard(inner)
        self.right, self.left = offline.CachedAgent(speak=True), offline.CachedAgent(speak=False)
        self.session = CallSession(
            "off01", self.guard, MemoryLedger(self._tool), self.right, self.left, self._emit
        )
        self.right.handler, self.left.handler = self.session.on_right, self.session.on_left

    def _tool(self, values: Values) -> dict[str, Any]:
        self.executed.append(values)
        return {"ok": True}

    async def _emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == kind]


@pytest.fixture
def clip(tmp_path, monkeypatch):
    pcm = audio.to_pcm(np.full(audio.RATE // 2, 0.1, dtype="float32"))
    path = tmp_path / "clip.wav"
    audio.write_wav(path, pcm)
    raw = {"amount_rupees": 2750, "day_of_month": None, "weekday": "tuesday", "phone": None}
    proposal = realtime_agent.AgentProposal({"amount_rupees": 2750, "weekday": "tuesday"}, raw, 900.0, 10.0)
    seen: list[str] = []

    async def propose(pcm24k: bytes, audio_sha: str | None = None, cache: Any = None) -> Any:
        seen.append(audio_sha or "")
        return proposal

    monkeypatch.setattr(realtime_agent, "propose", propose)
    monkeypatch.setattr(offline.asyncio, "sleep", _no_sleep(offline.asyncio.sleep))
    return path, pcm, seen


def _no_sleep(real: Any) -> Any:
    async def sleep(_: float) -> None:
        await real(0)

    return sleep


async def test_pass_commits_once_and_guard_hears_the_clip_itself(clip) -> None:
    path, pcm, seen = clip
    rig = Rig(("pass",))
    await offline.replay(rig.session, rig.guard, rig.right, rig.left, path)
    assert seen == [audio.sha(pcm)]
    assert rig.heard == [pcm]  # not the session's re-cut span, whose hash the cache has never seen
    assert rig.executed == [{"amount_rupees": 2750, "weekday": "tuesday"}]
    assert rig.of("left.committed")[0]["values"] == rig.executed[0]
    assert rig.of("agent.said")[0]["text"].startswith("Note kar liya")
    assert rig.events[-1]["type"] == "replay.done"


async def test_ask_speaks_the_question_and_executes_nothing(clip) -> None:
    path, _, _ = clip
    rig = Rig(("ask",))
    await offline.replay(rig.session, rig.guard, rig.right, rig.left, path)
    assert rig.executed == []
    assert rig.of("agent.said")[0]["text"] == rig.of("question.asked")[0]["text"]
    assert rig.events[-1]["type"] == "replay.done"


async def test_uncollected_clip_reports_and_stops(clip, monkeypatch) -> None:
    path, _, _ = clip

    async def miss(*_: Any, **__: Any) -> Any:
        raise offline.CacheMiss("x")

    monkeypatch.setattr(realtime_agent, "propose", miss)
    rig = Rig(("pass",))
    await offline.replay(rig.session, rig.guard, rig.right, rig.left, path)
    assert rig.executed == [] and rig.of("error") and rig.events[-1]["reason"] == "not_cached"
