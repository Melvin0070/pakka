"""gpt-transcribe, plain and with a domain prompt. The prompt names the domain only, never candidate values:
hinting the value under test would let the agent's own guess leak into the evidence."""

from __future__ import annotations

from typing import Any

from ..audio import wav_bytes
from ..types import Hypothesis
from ._openai import client
from .base import Source

MODEL = "gpt-transcribe"
LANGUAGES = ["hi", "en"]
DOMAIN_PROMPT = (
    "A phone call in India in Hindi, English or both. The caller may state an amount in rupees "
    "(hazaar, lakh, sava, saadhe, paune, dedh, dhai), a date or weekday, or a 10-digit mobile number."
)


async def _call(pcm24k: bytes, params: dict[str, Any]) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if params.get("prompt"):
        kw["prompt"] = params["prompt"]
    r = await client().audio.transcriptions.create(
        model=params["model"],
        file=("clip.wav", wav_bytes(pcm24k), "audio/wav"),
        extra_body={"languages": params["languages"]},
        **kw,
    )
    return {"text": r.text}


def _parser(name: str):
    def parse(resp: dict[str, Any], latency_ms: float) -> Hypothesis:
        return Hypothesis(
            source=name, family="openai-transcribe", text=resp["text"].strip(), latency_ms=latency_ms
        )

    return parse


def plain() -> Source:
    return Source(
        "gpt-transcribe",
        "openai-transcribe",
        {"model": MODEL, "languages": LANGUAGES},
        _call,
        _parser("gpt-transcribe"),
    )


def hinted() -> Source:
    name = "gpt-transcribe+hints"
    params = {"model": MODEL, "languages": LANGUAGES, "prompt": DOMAIN_PROMPT}
    return Source(name, "openai-transcribe", params, _call, _parser(name))
