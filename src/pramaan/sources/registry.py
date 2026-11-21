"""Configured recognisers and the deadline-bounded fan-out."""

from __future__ import annotations

import asyncio

from ..audio import sha
from ..cache import offline
from ..types import Hypothesis
from . import gpt4o_transcribe, gpt_transcribe, saaras, scribe, verbx
from .base import Source


def available_sources() -> list[Source]:
    out = [gpt_transcribe.plain(), gpt_transcribe.hinted(), gpt4o_transcribe.source()]
    # Offline every answer comes from the cache, so a vendor that was collected needs no key to be replayed.
    if verbx.enabled() or offline():
        out.append(verbx.source())
    if scribe.enabled():
        out.append(scribe.source())
    if saaras.enabled() or offline():
        out.append(saaras.source())
    return out


async def gather(
    pcm24k: bytes,
    deadline_ms: float | None,
    sources: list[Source] | None = None,
    audio_sha: str | None = None,
) -> tuple[list[Hypothesis], list[str]]:
    """Run every source concurrently. Returns (hypotheses in source order, absent source names).

    A source is absent if it failed, or if its latency exceeded the deadline. The latency test uses the
    originally recorded latency, so a cache replay drops exactly the sources a live call would have dropped.
    """
    srcs = available_sources() if sources is None else sources
    key = audio_sha or sha(pcm24k)
    results: dict[str, Hypothesis | None] = {}

    async def run(s: Source) -> None:
        try:
            if deadline_ms is None:
                results[s.name] = await s.hypothesis(pcm24k, key)
            else:
                async with asyncio.timeout(deadline_ms / 1000):
                    results[s.name] = await s.hypothesis(pcm24k, key)
        except TimeoutError:
            results[s.name] = None

    async with asyncio.TaskGroup() as tg:
        for s in srcs:
            tg.create_task(run(s))

    hyps: list[Hypothesis] = []
    absent: list[str] = []
    for s in srcs:
        h = results.get(s.name)
        if h is None or (deadline_ms is not None and h.latency_ms > deadline_ms):
            absent.append(s.name)
        else:
            hyps.append(h)
    return hyps, absent
