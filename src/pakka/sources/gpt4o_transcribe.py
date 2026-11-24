"""gpt-4o-transcribe with token logprobs.

Left alone (even with language="hi") it often writes Hindi speech in Urdu script, which nothing downstream
can read. A short Devanagari prompt fixes the script; it names no numbers, so it cannot bias the values.
"""

from __future__ import annotations

from typing import Any

from .. import lang
from ..audio import wav_bytes
from ..types import Hypothesis, Word
from ._openai import client
from .base import Source

NAME = "gpt-4o-transcribe"
SCRIPT_PROMPT = lang.HI.script_prompt


async def _call(pcm24k: bytes, params: dict[str, Any]) -> dict[str, Any]:
    r = await client().audio.transcriptions.create(
        model=params["model"],
        file=("clip.wav", wav_bytes(pcm24k), "audio/wav"),
        include=["logprobs"],
        response_format="json",
        language=params["language"],
        prompt=params["prompt"],
    )
    # Drop the per-token byte arrays: they triple the row size and the token text carries the same thing.
    lp = [[t.token, None if t.logprob is None else round(t.logprob, 4)] for t in (r.logprobs or [])]
    return {"text": r.text, "logprobs": lp}


def parse(resp: dict[str, Any], latency_ms: float) -> Hypothesis:
    words = tuple(Word(text=tok, logprob=lp) for tok, lp in resp.get("logprobs", []))
    return Hypothesis(
        source=NAME, family="openai-transcribe", text=resp["text"].strip(), latency_ms=latency_ms, words=words
    )


def source() -> Source:
    cur = lang.get()
    return Source(
        NAME,
        "openai-transcribe",
        {"model": "gpt-4o-transcribe", "language": cur.code, "prompt": cur.script_prompt},
        _call,
        parse,
    )
