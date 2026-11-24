from __future__ import annotations

from functools import cache

from openai import AsyncOpenAI


@cache
def client() -> AsyncOpenAI:
    # Retries are ours (base.with_retries), so the SDK's own are off to keep latency honest.
    return AsyncOpenAI(max_retries=0, timeout=60.0)
