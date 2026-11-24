"""Shared adapter plumbing: the Source shape, retries, and the cache round trip."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import openai

from ..audio import sha
from ..cache import Cache, CacheMiss, Entry, Timed, default_cache
from ..types import Family, Hypothesis

log = logging.getLogger("pakka.sources")

TRIES = 2
BACKOFF_S = 1.5


class PermanentError(RuntimeError):
    """A failure that will repeat on retry (bad request, model produced no tool call). Cached as an error row."""


def is_transient(e: BaseException) -> bool:
    if isinstance(e, PermanentError | CacheMiss):
        return False
    if isinstance(e, openai.APIStatusError):
        return e.status_code == 429 or e.status_code >= 500
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code == 429 or e.response.status_code >= 500
    return True  # timeouts, connection resets, websocket drops


def as_permanent(e: BaseException) -> BaseException:
    if isinstance(e, openai.APIStatusError | httpx.HTTPStatusError) and not is_transient(e):
        return PermanentError(f"{type(e).__name__}: {e}")
    return e


async def with_retries(fn: Callable[[], Awaitable[Any]], tries: int = TRIES) -> Timed:
    """Latency reported is the successful attempt's only: failed attempts and backoff are not vendor latency."""
    for attempt in range(tries):
        t0 = time.perf_counter()
        try:
            resp = await fn()
            return Timed(resp, (time.perf_counter() - t0) * 1000)
        except Exception as e:
            perm = as_permanent(e)
            if perm is not e:
                raise perm from e
            if attempt + 1 >= tries or not is_transient(e):
                raise
            await asyncio.sleep(BACKOFF_S * (attempt + 1))
    raise AssertionError("unreachable")


@dataclass
class Source:
    """One recogniser. `call` hits the network and returns a compact JSON-able response; `parse` turns a
    response (fresh or cached) into a Hypothesis. Keeping them apart lets tests parse recorded fixtures."""

    name: str
    family: Family
    params: dict[str, Any]
    call: Callable[[bytes, dict[str, Any]], Awaitable[Any]]
    parse: Callable[[Any, float], Hypothesis]
    cache: Cache | None = field(default=None, repr=False)

    async def entry(self, pcm24k: bytes, audio_sha: str | None = None) -> Entry:
        c = self.cache or default_cache()
        return await c.cached(
            audio_sha or sha(pcm24k),
            self.name,
            self.params,
            lambda: with_retries(lambda: self.call(pcm24k, self.params)),
            cache_errors=PermanentError,
        )

    async def hypothesis(self, pcm24k: bytes, audio_sha: str | None = None) -> Hypothesis | None:
        """None on any failure (logged). CacheMiss propagates: an offline hole is a bug, not an absence."""
        try:
            e = await self.entry(pcm24k, audio_sha)
            if e.is_error:
                return None
            return self.parse(e.response, e.latency_ms)
        except CacheMiss:
            raise
        except Exception as ex:
            log.warning("source %s failed: %s: %s", self.name, type(ex).__name__, str(ex)[:200])
            return None
