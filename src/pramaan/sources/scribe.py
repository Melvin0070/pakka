"""ElevenLabs Scribe speech-to-text (word timestamps + logprobs).

UNTESTED against the live API (no key during the build); written from the public REST docs.
Enabled only when ELEVENLABS_API_KEY is set.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..audio import wav_bytes
from ..types import Hypothesis, Word
from .base import Source

NAME = "scribe"
URL = "https://api.elevenlabs.io/v1/speech-to-text"


def enabled() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


async def _call(pcm24k: bytes, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as http:
        r = await http.post(
            URL,
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            data={
                "model_id": params["model_id"],
                "timestamps_granularity": "word",
                "tag_audio_events": "false",
            },
            files={"file": ("clip.wav", wav_bytes(pcm24k), "audio/wav")},
        )
        r.raise_for_status()
        return compact(r.json())


def compact(body: dict[str, Any]) -> dict[str, Any]:
    words = [
        [w.get("text", ""), w.get("start"), w.get("end"), w.get("logprob")]
        for w in body.get("words", [])
        if w.get("type", "word") == "word"
    ]
    return {"text": body.get("text", ""), "language": body.get("language_code"), "words": words}


def parse(resp: dict[str, Any], latency_ms: float) -> Hypothesis:
    words = tuple(Word(text=t, start_s=s, end_s=e, logprob=lp) for t, s, e, lp in resp.get("words", []))
    return Hypothesis(
        source=NAME, family="elevenlabs", text=resp["text"].strip(), latency_ms=latency_ms, words=words
    )


def source() -> Source:
    return Source(NAME, "elevenlabs", {"model_id": os.environ.get("SCRIBE_MODEL", "scribe_v1")}, _call, parse)
