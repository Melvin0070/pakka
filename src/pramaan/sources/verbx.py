"""VerbX speech-to-text (model verbx-vocaline). JSON body with base64 WAV; multipart and raw audio get 415.

language is always "hi": "en" times out server-side, and "hi" still transcribes English speech (in Devanagari).
The vendor's `confidence` is a constant, so it is not kept. Enabled only when VERBX_API_KEY is set.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from ..audio import wav_bytes
from ..types import Hypothesis
from .base import Source

NAME = "verbx-vocaline"
URL = "https://api.verbxeco.com/v1/stt"


def enabled() -> bool:
    return bool(os.environ.get("VERBX_API_KEY"))


async def _call(pcm24k: bytes, params: dict[str, Any]) -> dict[str, Any]:
    body = {
        "audio_base64": base64.b64encode(wav_bytes(pcm24k)).decode(),
        "mime_type": "audio/wav",
        "language": params["language"],
    }
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(URL, headers={"X-API-Key": os.environ["VERBX_API_KEY"]}, json=body)
        r.raise_for_status()  # 503 stt.timeout is transient and retried by base.with_retries
        return compact(r.json())


def compact(body: dict[str, Any]) -> dict[str, Any]:
    return {"text": body.get("text", ""), "model": body.get("model"), "server_ms": body.get("latency_ms")}


def parse(resp: dict[str, Any], latency_ms: float) -> Hypothesis:
    return Hypothesis(source=NAME, family="verbx", text=resp["text"].strip(), latency_ms=latency_ms)


def source() -> Source:
    return Source(NAME, "verbx", {"model": "verbx-vocaline", "language": "hi"}, _call, parse)
