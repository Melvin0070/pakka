"""FastAPI shell: browser WebSocket <-> CallSession <-> two OpenAI Realtime sessions.

Run: uvicorn pramaan.live.server:app --port 8765
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import time
import uuid
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import soxr
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..cache import offline
from ..pipeline import Guard
from ..types import Values
from . import offline as offline_replay
from .fake_guard import FakeGuard
from .ledger import make_ledger
from .record import router as record_router
from .ring import RATE
from .session import CallSession
from .tooling import LEFT_INSTRUCTIONS, RIGHT_INSTRUCTIONS, TOOL

ROOT = Path(__file__).resolve().parents[3]
UI = ROOT / "ui"
MODEL = os.environ.get("PRAMAAN_REALTIME_MODEL", "gpt-realtime-2.1")
VOICE = os.environ.get("PRAMAAN_VOICE", "marin")
REPLAY_ROOTS = (ROOT / "data" / "clips", ROOT / "demo", ROOT / "g0" / "clips")
FRAME_MS = 100
FRAME_BYTES = RATE * 2 * FRAME_MS // 1000

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("pramaan.live")


@contextlib.asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    warm = getattr(make_guard(), "warm", None)
    if warm is not None:
        # Load the acoustic model now so the first caller turn does not pay for it.
        with contextlib.suppress(Exception):
            await asyncio.to_thread(warm)
    yield


app = FastAPI(title="Pramaan live guard", lifespan=_lifespan)

_guard: Guard | None = None
_health: tuple[float, bool, str] = (0.0, False, "")
_crm: list[dict[str, Any]] = []  # what the guarded agent actually executed, newest last
_sessions: dict[str, CallSession] = {}


def make_guard() -> Guard:
    """The real pipeline when it imports and constructs; otherwise scripted evidence, flagged in the UI."""
    global _guard
    if _guard is None:
        try:
            from ..pipeline import Pipeline  # type: ignore[attr-defined]

            _guard = Pipeline()
        except Exception as e:  # noqa: BLE001 - any failure here must degrade to the labelled fake
            log.info(json.dumps({"event": "guard.fallback", "reason": f"{type(e).__name__}: {e}"}))
            _guard = FakeGuard()
    return _guard


def guard_kind(guard: Guard) -> str:
    return "fake" if getattr(guard, "is_fake", False) else "pipeline"


def _log_commitment(values: Values) -> dict[str, Any]:
    _crm.append({"at": time.time(), **values})
    return {"ok": True, "row": len(_crm)}


# ---- replayable clips


def _clips() -> list[dict[str, Any]]:
    manifest = ROOT / "data" / "manifest.jsonl"
    out: list[dict[str, Any]] = []
    prompts_file = ROOT / "data" / "prompts.jsonl"
    says: dict[str, str] = {}
    if prompts_file.exists():
        says = {
            p["id"]: p.get("say", "")
            for p in map(json.loads, filter(str.strip, prompts_file.read_text().splitlines()))
        }
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            out.append({k: row.get(k) for k in ("clip_id", "speaker", "condition", "path", "truth")})
            out[-1]["say"] = says.get(row.get("prompt_id"))
    prompts = ROOT / "g0" / "prompts.json"
    truth = {p["id"]: p for p in json.loads(prompts.read_text())} if prompts.exists() else {}
    for p in sorted((ROOT / "g0" / "clips").glob("*.wav")):
        speaker, pid, cond = (p.stem.split("_") + ["", ""])[:3]
        out.append({"clip_id": p.stem, "speaker": speaker, "condition": cond, "path": str(p.relative_to(ROOT)),
                    "truth": truth.get(pid, {}).get("truth"), "say": truth.get(pid, {}).get("say")})  # fmt: skip
    for p in sorted((ROOT / "demo").glob("*.wav")) if (ROOT / "demo").exists() else []:
        out.insert(
            0,
            {
                "clip_id": p.stem,
                "speaker": "demo",
                "condition": "demo",
                "path": str(p.relative_to(ROOT)),
                "truth": None,
            },
        )
    return out


def _resolve_clip(ref: str) -> Path:
    # demo/ holds committed copies of the README clips; the full set under data/clips is not in the repo.
    known = [c["path"] for c in _clips() if c["clip_id"] == ref]
    path = (ROOT / next((p for p in known if (ROOT / p).exists()), ref)).resolve()
    if (
        not any(path.is_relative_to(r.resolve()) for r in REPLAY_ROOTS)
        or path.suffix != ".wav"
        or not path.exists()
    ):
        raise FileNotFoundError(ref)
    return path


def _read_pcm24k(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path.name}: need 16-bit PCM")
    pcm = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if rate != RATE:
        pcm = soxr.resample(pcm, rate, RATE).astype(np.int16)
    return pcm.tobytes()


# ---- HTTP


@app.get("/api/health")
async def health() -> dict[str, Any]:
    global _health
    key = os.environ.get("OPENAI_API_KEY", "")
    if key and not offline() and time.time() - _health[0] > 60:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"https://api.openai.com/v1/models/{MODEL}", headers={"Authorization": f"Bearer {key}"}
                )
            _health = (
                time.time(),
                r.status_code == 200,
                "" if r.status_code == 200 else f"HTTP {r.status_code}",
            )
        except httpx.HTTPError as e:
            _health = (time.time(), False, type(e).__name__)
    guard = make_guard()
    models = ROOT / "models"
    return {
        "offline": offline(),
        "key_present": bool(key),
        "model": MODEL,
        "model_reachable": _health[1],
        "model_error": _health[2],
        "guard": guard_kind(guard),
        "policy_hash": getattr(getattr(guard, "policy", None), "hash", ""),
        "witness_loaded": getattr(guard, "witness", None) is not None,
        "witness_files": models.exists() and any(models.rglob("*.onnx")),
        "results_present": (ROOT / "results" / "headline.json").exists(),
    }


@app.get("/api/results")
async def results(set: str = "synthetic") -> JSONResponse:
    path = (
        ROOT
        / "results"
        / {"human": "human.json", "fresh": "fresh.json", "fresh2": "fresh2.json"}.get(set, "headline.json")
    )
    # null, not 404: the page shows its own "no results yet" state and the console stays clean.
    return JSONResponse(json.loads(path.read_text()) if path.exists() else None)


@app.get("/api/scenarios")
async def scenarios() -> JSONResponse:
    path = ROOT / "demo" / "scenarios.json"
    return JSONResponse(json.loads(path.read_text()) if path.exists() else [])


@app.get("/api/analysis")
async def analysis() -> JSONResponse:
    path = ROOT / "results" / "analysis.json"
    return JSONResponse(json.loads(path.read_text()) if path.exists() else None)


@app.get("/api/clips")
async def clips() -> list[dict[str, Any]]:
    return _clips()


@app.get("/api/bundles/{bundle_id}")
async def bundle(bundle_id: str) -> JSONResponse:
    for session in _sessions.values():
        if bundle_id in session.judgements:
            return JSONResponse(session.judgements[bundle_id].model_dump(mode="json"))
    store = ROOT / "results" / "bundles.jsonl"
    if store.exists():
        for line in store.read_text().splitlines():
            if bundle_id in line[:400] and json.loads(line).get("id") == bundle_id:
                return JSONResponse(json.loads(line))
    raise HTTPException(404, "unknown bundle")


@app.get("/api/crm")
async def crm() -> list[dict[str, Any]]:
    return _crm[-50:]


# ---- Realtime


class RealtimeLink:
    def __init__(self, ws: Any) -> None:
        self.ws = ws

    async def send(self, event: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(event))


def _session_update(instructions: str, speak: bool) -> dict[str, Any]:
    audio: dict[str, Any] = {
        "input": {
            "format": {"type": "audio/pcm", "rate": RATE},
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": 500,
                "create_response": True,
                "interrupt_response": True,
            },
        }
    }
    if speak:
        audio["output"] = {"format": {"type": "audio/pcm", "rate": RATE}, "voice": VOICE}
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "output_modalities": ["audio"] if speak else ["text"],
            "instructions": instructions,
            "audio": audio,
            "tools": [TOOL],
            "tool_choice": "auto",
        },
    }


async def _connect(instructions: str, speak: bool) -> Any:
    ws = await websockets.connect(
        f"wss://api.openai.com/v1/realtime?model={MODEL}",
        additional_headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        max_size=None,
    )
    await ws.send(json.dumps(_session_update(instructions, speak)))
    return ws


async def _replay(session: CallSession, paths: list[Path], idle_s: float = 20.0) -> None:
    """Feed clips as if spoken live: the first at once, each later one as the answer to a question."""
    queue = [_read_pcm24k(p) for p in paths]
    names = [p.stem for p in paths]
    silence = b"\0" * FRAME_BYTES
    current, pos, last_voice = b"", 0, session.clock()
    next_frame = session.clock()
    first = True
    final_at: float | None = None
    while True:
        now = session.clock()
        if (
            pos >= len(current)
            and queue
            and (
                first
                or (
                    session.awaiting_answer and session.question_spoken and now > session.agent_quiet_at + 0.6
                )
            )
        ):
            current, pos, first = queue.pop(0), 0, False
            session.awaiting_answer = False
            await session.emit(
                "replay.clip", clip=names.pop(0), duration_ms=len(current) * 1000 // (RATE * 2)
            )
        if pos < len(current):
            frame = current[pos : pos + FRAME_BYTES]
            pos += FRAME_BYTES
            last_voice = now
            await session.emit("caller.audio", audio=base64.b64encode(frame).decode())
        else:
            frame = silence
            if session.final and final_at is None:
                final_at = now
            spoken = session.closing_spoken and now > session.agent_quiet_at + 1.0
            done = final_at is not None and (spoken or now - final_at > 10)
            if done or now - last_voice > idle_s:
                await session.emit("replay.done", reason="settled" if done else "idle")
                return
        await session.caller_audio(frame)
        next_frame += FRAME_MS / 1000
        await asyncio.sleep(max(next_frame - session.clock(), 0))


@app.websocket("/ws")
async def ws(browser: WebSocket) -> None:
    await browser.accept()
    params = browser.query_params
    session_id = uuid.uuid4().hex[:8]
    outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        outbox.put_nowait(event)

    async def writer() -> None:
        while True:
            await browser.send_text(json.dumps(await outbox.get(), ensure_ascii=False, default=str))

    off = offline()
    problem = ""
    if off and not params.get("replay"):
        problem = "Offline mode replays recorded calls only; the microphone needs the network."
    elif not off and not os.environ.get("OPENAI_API_KEY"):
        problem = "OPENAI_API_KEY is not set"
    if problem:
        await browser.send_text(json.dumps({"type": "error", "turn_id": "", "message": problem}))
        await browser.close()
        return
    try:
        replay = [_resolve_clip(r) for r in params.get("replay", "").split(",") if r]
    except (FileNotFoundError, ValueError) as e:
        await browser.send_text(json.dumps({"type": "error", "turn_id": "", "message": f"unknown clip: {e}"}))
        await browser.close()
        return
    with_left = params.get("left", "1") != "0"
    guard = make_guard()

    right_ws = left_ws = None
    session: CallSession | None = None
    try:
        if off:
            guard = offline_replay.ClipGuard(guard)
            right = offline_replay.CachedAgent(speak=True)
            left = offline_replay.CachedAgent(speak=False) if with_left else None
            session = CallSession(session_id, guard, make_ledger(_log_commitment), right, left, emit)
            right.handler = session.on_right
            if left:
                left.handler = session.on_left
        else:
            right_ws, left_ws = await asyncio.gather(
                _connect(RIGHT_INSTRUCTIONS, speak=True),
                _connect(LEFT_INSTRUCTIONS, speak=False) if with_left else asyncio.sleep(0),
            )
            session = CallSession(session_id, guard, make_ledger(_log_commitment), RealtimeLink(right_ws),
                                  RealtimeLink(left_ws) if left_ws else None, emit)  # fmt: skip
        _sessions[session_id] = session
        while len(_sessions) > 20:
            _sessions.pop(next(iter(_sessions)))
        await session.emit(
            "session.ready", guard=guard_kind(guard), model=MODEL,
            mode="offline-replay" if off else "replay" if replay else "mic",
            policy_hash=getattr(getattr(guard, "policy", None), "hash", ""),
            deadline_ms=getattr(getattr(guard, "policy", None), "deadline_ms", None), session_id=session_id,
        )  # fmt: skip

        async def pump(ws_: Any, handler: Any) -> None:
            async for raw in ws_:
                await handler(json.loads(raw))

        async def mic() -> None:
            while True:
                msg = await browser.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes"):
                    await session.caller_audio(msg["bytes"])
                elif msg.get("text") and json.loads(msg["text"]).get("type") == "stop":
                    return

        async def watch_disconnect() -> None:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                while (await browser.receive())["type"] != "websocket.disconnect":
                    pass

        if isinstance(guard, offline_replay.ClipGuard):
            source = asyncio.create_task(offline_replay.replay(session, guard, right, left, replay[0]))
        else:
            source = asyncio.create_task(_replay(session, replay) if replay else mic())
        tasks = [source, asyncio.create_task(writer())]
        if right_ws:
            tasks.append(asyncio.create_task(pump(right_ws, session.on_right)))
        if left_ws:
            tasks.append(asyncio.create_task(pump(left_ws, session.on_left)))
        if replay:
            tasks.append(asyncio.create_task(watch_disconnect()))
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                log.info(
                    json.dumps({"session": session_id, "event": "task.error", "error": repr(t.exception())})
                )
        await asyncio.sleep(0.2)  # let the writer drain the last events
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        pass
    except Exception as e:  # noqa: BLE001 - report to the browser rather than dying silently
        log.info(json.dumps({"session": session_id, "event": "session.error", "error": repr(e)}))
        with contextlib.suppress(Exception):
            await browser.send_text(
                json.dumps({"type": "error", "turn_id": "", "message": f"{type(e).__name__}: {e}"})
            )
    finally:
        if session:
            await session.close()
        for w in (right_ws, left_ws):
            if w is not None:
                with contextlib.suppress(Exception):
                    await w.close()
        with contextlib.suppress(Exception):
            await browser.close()


app.include_router(record_router)
app.mount("/", StaticFiles(directory=UI, html=True), name="ui")
