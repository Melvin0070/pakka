"""Preflight before a demo: run it, read the lines marked FAIL. Exits non-zero if the live call cannot work."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.environ.get("PRAMAAN_REALTIME_MODEL", "gpt-realtime-2.1")
URL = "http://127.0.0.1:8765"


def line(ok: bool | None, what: str, detail: str = "") -> bool:
    tag = {True: " ok ", False: "FAIL", None: "warn"}[ok]
    print(f"[{tag}] {what}{': ' + detail if detail else ''}")
    return ok is not False


async def realtime(key: str) -> tuple[bool, str]:
    t0 = time.monotonic()
    try:
        async with websockets.connect(
            f"wss://api.openai.com/v1/realtime?model={MODEL}",
            additional_headers={"Authorization": f"Bearer {key}"},
            open_timeout=6,
        ) as ws:
            ev = json.loads(await asyncio.wait_for(ws.recv(), 6))
        ok = ev.get("type") == "session.created"
        return ok, f"{MODEL} session in {(time.monotonic() - t0) * 1000:.0f} ms" if ok else str(ev)[:120]
    except Exception as e:  # noqa: BLE001 - any failure is the answer
        return False, f"{type(e).__name__}: {e}"[:160]


async def main() -> int:
    key = os.environ.get("OPENAI_API_KEY", "")
    hard = [line(bool(key), "OPENAI_API_KEY set")]
    if key:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                r = await client.get(
                    "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}
                )
            hard.append(line(r.status_code == 200, "API key valid", f"HTTP {r.status_code}"))
        except httpx.HTTPError as e:
            hard.append(line(False, "API key valid", type(e).__name__))
        hard.append(line(*await realtime(key)))

    cache = ROOT / "data" / "cache.sqlite"
    line(
        cache.exists() or None,
        "replay cache",
        str(cache.relative_to(ROOT)) if cache.exists() else "missing: offline eval will not run",
    )
    onnx = sorted((ROOT / "models").rglob("*.onnx")) if (ROOT / "models").exists() else []
    line(
        bool(onnx) or None,
        "acoustic model files",
        onnx[0].name if onnx else "missing: run scripts/fetch_model.py",
    )
    res = ROOT / "results" / "headline.json"
    line(res.exists() or None, "results/headline.json", "" if res.exists() else "missing: run make eval")
    clips = len(list((ROOT / "data" / "clips").rglob("*.wav"))) + len(
        list((ROOT / "g0" / "clips").glob("*.wav"))
    )
    line(clips > 0 or None, "replayable clips", str(clips))
    try:
        from pramaan.pipeline import Pipeline  # type: ignore[attr-defined]  # noqa: F401

        line(True, "evidence pipeline importable")
    except Exception as e:  # noqa: BLE001
        line(
            None, "evidence pipeline", f"not loaded ({type(e).__name__}); the server will show FAKE EVIDENCE"
        )
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            h = (await client.get(f"{URL}/api/health")).json()
        line(True, "server already running", f"guard={h.get('guard')}")
    except httpx.HTTPError:
        line(None, "server", "not running yet (make serve)")
    print(
        f"\nOpen {URL} in Chrome, allow the microphone, and use a headset. Mic level is checked in the page."
    )
    return 0 if all(hard) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
