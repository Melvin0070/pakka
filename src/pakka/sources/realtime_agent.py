"""Arm A: the agent being guarded. One audio turn into gpt-realtime-2.1, which must call log_commitment."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import websockets

from .. import lang
from ..audio import sha
from ..cache import Cache, CacheMiss, default_cache
from ..types import CORE_SLOTS, DIGIT_SLOTS, SLOTS, Values
from .base import PermanentError, log, with_retries

NAME = "gpt-realtime-2.1"
MODEL = "gpt-realtime-2.1"
CALL_TIMEOUT_S = 45.0

# Kept identical to g0/common.py so the G0 numbers and the full dataset measure the same agent.
TOOL: dict[str, Any] = {
    "type": "function",
    "name": "log_commitment",
    "description": "Record what the caller committed to on this call. Fill only the values the caller actually said.",
    "parameters": {
        "type": "object",
        "properties": {
            "amount_rupees": {
                "type": ["integer", "null"],
                "description": "Amount in rupees as a plain integer.",
            },
            "day_of_month": {
                "type": ["integer", "null"],
                "description": "Day of the month (1-31) if the caller gave a date.",
            },
            "weekday": {
                "type": ["string", "null"],
                "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", None],
            },
            "phone": {
                "type": ["string", "null"],
                "description": "10-digit Indian mobile number, digits only.",
            },
        },
        "required": list(CORE_SLOTS),
    },
}
INSTRUCTIONS = lang.HI.agent_instructions
PARAMS: dict[str, Any] = {
    "model": MODEL,
    "instructions": INSTRUCTIONS,
    "tool": TOOL,
    "tool_choice": "required",
}


def params() -> dict[str, Any]:
    """PARAMS for the language in force. The Hindi dict is the constant above, unchanged, so its cache key holds."""
    return {**PARAMS, "instructions": lang.get().agent_instructions}


@dataclass(frozen=True)
class AgentProposal:
    values: Values  # normalised tool arguments; null/empty slots omitted
    raw: dict[str, Any]
    latency_ms: float  # connect + session setup + response, as recorded
    response_ms: float | None = None  # response.create -> response.done only


def norm(slot: str, v: Any) -> int | str | None:
    """Same light normalisation as g0/common.py: the agent's own output, not the guard's normaliser."""
    if v in (None, "", "null"):
        return None
    if slot == "phone":
        d = "".join(c for c in str(v) if c.isdigit())
        return d[-10:] if len(d) >= 10 else d
    if slot in DIGIT_SLOTS:
        return "".join(c for c in str(v) if c.isdigit()) or None
    if slot == "weekday":
        return str(v).strip().lower()
    try:
        return int(v)
    except (TypeError, ValueError):
        return str(v)


def parse(resp: dict[str, Any], latency_ms: float) -> AgentProposal:
    args = resp["arguments"]
    values: Values = {}
    for slot in SLOTS:
        v = norm(slot, args.get(slot))
        if v is not None:
            values[slot] = v
    return AgentProposal(values=values, raw=args, latency_ms=latency_ms, response_ms=resp.get("response_ms"))


async def _call(pcm24k: bytes, params: dict[str, Any]) -> dict[str, Any]:
    url = f"wss://api.openai.com/v1/realtime?model={params['model']}"
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    async with (
        asyncio.timeout(CALL_TIMEOUT_S),
        websockets.connect(url, additional_headers=headers, max_size=None) as ws,
    ):
        session = {
            "type": "realtime",
            "output_modalities": ["text"],
            "instructions": params["instructions"],
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None}},
            "tools": [params["tool"]],
            "tool_choice": params["tool_choice"],
        }
        await ws.send(json.dumps({"type": "session.update", "session": session}))
        item = {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_audio", "audio": base64.b64encode(pcm24k).decode()}],
        }
        await ws.send(json.dumps({"type": "conversation.item.create", "item": item}))
        await ws.send(json.dumps({"type": "response.create"}))
        t0 = time.perf_counter()
        async for raw in ws:
            ev = json.loads(raw)
            if ev["type"] == "error":
                err = ev["error"]
                msg = f"{err.get('type')}/{err.get('code')}: {err.get('message')}"
                if err.get("type") == "invalid_request_error":
                    raise PermanentError(msg)
                raise RuntimeError(msg)
            if ev["type"] == "response.done":
                resp = ev["response"]
                for out in resp.get("output", []):
                    if out.get("type") == "function_call":
                        # The cache records connect-to-done; response_ms is the part a live, already-open
                        # session would actually wait for.
                        return {
                            "name": out.get("name"),
                            "arguments": json.loads(out["arguments"]),
                            "response_ms": round((time.perf_counter() - t0) * 1000, 1),
                        }
                if resp.get("status") == "failed":
                    raise RuntimeError(f"response failed: {resp.get('status_details')}")
                raise PermanentError(f"no tool call (status {resp.get('status')})")
    raise RuntimeError("socket closed before response.done")


async def propose(
    pcm24k: bytes, audio_sha: str | None = None, cache: Cache | None = None
) -> AgentProposal | None:
    """The agent's proposed tool arguments, or None if it failed. CacheMiss propagates (offline hole)."""
    c = cache or default_cache()
    p = params()
    try:
        e = await c.cached(
            audio_sha or sha(pcm24k),
            NAME,
            p,
            lambda: with_retries(lambda: _call(pcm24k, p)),
            cache_errors=PermanentError,
        )
        return None if e.is_error else parse(e.response, e.latency_ms)
    except CacheMiss:
        raise
    except Exception as ex:
        log.warning("agent %s failed: %s: %s", NAME, type(ex).__name__, str(ex)[:200])
        return None
