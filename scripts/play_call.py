"""Play one recorded call against a running server and print what each side did. No browser needed.

Usage: uv run python scripts/play_call.py [call_id ...] [--url http://127.0.0.1:8765]
With no call id it plays every call the server lists under /api/scenarios.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx
import websockets

QUIET = {"caller.audio", "agent.audio", "ledger", "turn.started", "turn.ended", "replay.clip", "right.held"}


def show(values: Any) -> str:
    return json.dumps(values, ensure_ascii=False) if values else "nothing"


def describe(ev: dict[str, Any]) -> str | None:
    kind = ev.get("type", "")
    if kind == "session.ready":
        return f"mode {ev.get('mode')}, guard {ev.get('guard')}, policy {ev.get('policy_hash')}"
    if kind == "left.committed":
        return f"WITHOUT PRAMAAN executed  {show(ev.get('values'))}"
    if kind == "right.proposed":
        return f"with Pramaan: held        {show(ev.get('values'))}"
    if kind == "evidence":
        heard = [
            f"    {t.get('source')} [{t.get('family')}] {round(t.get('latency_ms') or 0)} ms"
            f"{'' if t.get('in_time') else ' (missed the deadline)'}: {show(t.get('values'))}"
            for t in ev.get("timings", [])
        ]
        return "evidence\n" + "\n".join(heard)
    if kind == "decision":
        slots = ", ".join(
            f"{s.get('slot')}={s.get('verdict')} ({s.get('reason')})" for s in ev.get("slots", [])
        )
        return f"decision {str(ev.get('verdict')).upper()}: {slots}"
    if kind == "right.committed":
        fixed = f"  (model proposed {show(ev['repaired_from'])})" if ev.get("repaired_from") else ""
        return f"WITH PRAMAAN executed     {show(ev.get('values'))}{fixed}"
    if kind == "agent.said":
        return f"agent says: {ev.get('text')}"
    if kind == "error":
        return f"ERROR {ev.get('message')}"
    return None


async def play(base: str, call: dict[str, Any]) -> bool:
    print(f"\n== {call['id']}: {call.get('title', '')}")
    if call.get("say"):
        print(f"caller said: {call['say']}\ntruth:       {show(call.get('truth'))}")
    clips = ",".join(c for c in (call["id"], call.get("answer")) if c)
    ok = True
    async with websockets.connect(f"{base.replace('http', 'ws', 1)}/ws?replay={clips}", max_size=None) as ws:
        try:
            while True:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 60))
                kind = ev.get("type", "")
                if kind in QUIET:
                    continue
                line = describe(ev)
                if line:
                    print(line)
                if kind == "error":
                    ok = False
                if kind in ("replay.done", "error"):
                    break
        except (TimeoutError, websockets.ConnectionClosed):
            pass
    return ok


async def main() -> int:
    args = sys.argv[1:]
    base = "http://127.0.0.1:8765"
    if "--url" in args:
        at = args.index("--url")
        base = args[at + 1].rstrip("/")
        del args[at : at + 2]
    async with httpx.AsyncClient(timeout=30) as client:
        health = (await client.get(f"{base}/api/health")).json()
        listed = (await client.get(f"{base}/api/scenarios")).json()
    print(
        f"server {base}: {'keyless replay' if health.get('offline') else 'live models'}, guard {health.get('guard')}"
    )
    calls = [next((c for c in listed if c["id"] == a), {"id": a}) for a in args] if args else listed
    results = [await play(base, c) for c in calls]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
