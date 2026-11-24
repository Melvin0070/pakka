"""Sarvam speech-to-text.

Enabled only when SARVAM_API_KEY is set. Default mode with hi-IN keeps numbers as Devanagari words, which
the acoustic witness needs for sentence context; "codemix" mode would return digits and Latin script. Sarvam returns no word confidences, so `words` stays empty.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .. import lang
from ..audio import RATE, resample, wav_bytes
from ..types import Hypothesis
from .base import Source

NAME = "saaras"
URL = "https://api.sarvam.ai/speech-to-text"


def enabled() -> bool:
    return bool(os.environ.get("SARVAM_API_KEY"))


async def _call(pcm24k: bytes, params: dict[str, Any]) -> dict[str, Any]:
    # Sarvam is tuned for 16 kHz telephony-ish input; sending 16 kHz also halves the upload.
    wav = wav_bytes(resample(pcm24k, RATE, 16_000), 16_000)
    async with httpx.AsyncClient(timeout=60.0) as http:
        r = await http.post(
            URL,
            headers={"api-subscription-key": os.environ["SARVAM_API_KEY"]},
            data={"model": params["model"], "language_code": params["language_code"]},
            files={"file": ("clip.wav", wav, "audio/wav")},
        )
        r.raise_for_status()
        return compact(r.json())


def compact(body: dict[str, Any]) -> dict[str, Any]:
    return {"text": body.get("transcript", ""), "language": body.get("language_code")}


def parse(resp: dict[str, Any], latency_ms: float) -> Hypothesis:
    return Hypothesis(source=NAME, family="sarvam", text=resp["text"].strip(), latency_ms=latency_ms)


def source() -> Source:
    params = {"model": os.environ.get("SARVAM_MODEL", "saaras:v3"), "language_code": lang.get().sarvam_code}
    return Source(NAME, "sarvam", params, _call, parse)
