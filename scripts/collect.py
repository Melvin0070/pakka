"""Run the agent (arm A) and every configured recogniser over the manifest, filling data/cache.sqlite.

Phone and noisy clips all; clean clips for a fixed 100-clip subset. Resumable: cached rows are not re-requested.
Usage: uv run python scripts/collect.py [--concurrency 12] [--retry-errors] [--limit N] [--manifest PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from collections import Counter
from pathlib import Path

from pramaan.audio import read_pcm24k
from pramaan.cache import default_cache
from pramaan.sources import realtime_agent
from pramaan.sources.base import Source
from pramaan.sources.registry import available_sources

ROOT = Path(__file__).resolve().parents[1]
CLEAN_SUBSET = 100
SEED = 20261121


def select(manifest: list[dict]) -> list[dict]:
    clean = sorted((r for r in manifest if r["condition"] == "clean"), key=lambda r: r["clip_id"])
    keep = {r["clip_id"] for r in random.Random(SEED).sample(clean, min(CLEAN_SUBSET, len(clean)))}
    return [r for r in manifest if r["condition"] != "clean" or r["clip_id"] in keep]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument(
        "--retry-errors", action="store_true", help="drop cached permanent-error rows and retry them"
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--manifest", default="data/manifest.jsonl")
    ap.add_argument("--verbose", action="store_true", help="log each failed call")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING if args.verbose else logging.ERROR)

    cache = default_cache()
    if args.retry_errors:
        print(f"dropped {cache.delete_errors()} cached error rows")
    manifest = [json.loads(line) for line in (ROOT / args.manifest).read_text().splitlines() if line]
    clips = select(manifest)[: args.limit or None]
    sources = available_sources()
    names = [realtime_agent.NAME] + [s.name for s in sources]
    print(f"{len(clips)} clips x {len(names)} sources: {', '.join(names)}")

    sem_rt = asyncio.Semaphore(max(2, args.concurrency // 2))  # realtime sessions are the scarce resource
    sem = asyncio.Semaphore(args.concurrency)
    # Small vendors get their own, lower cap so they do not throttle or starve the OpenAI calls.
    vendor_cap = {"verbx-vocaline": 4, "saaras": 3}
    # Pacing lives here, not in the adapter: waiting inside the adapter would be recorded as vendor latency.
    vendor_per_min = {"verbx-vocaline": 30}  # plan limit is 60/min, shared with anyone else on the key
    next_slot: dict[str, float] = {}
    pace_lock = asyncio.Lock()

    async def pace(name: str) -> None:
        if name not in vendor_per_min:
            return
        async with pace_lock:
            now = time.monotonic()
            t = max(now, next_slot.get(name, 0.0))
            next_slot[name] = t + 60.0 / vendor_per_min[name]
        await asyncio.sleep(t - now)

    sems = {s.name: asyncio.Semaphore(vendor_cap[s.name]) if s.name in vendor_cap else sem for s in sources}
    ok: Counter[str] = Counter()
    fail: Counter[str] = Counter()
    done = 0
    t0 = time.monotonic()

    async def one_source(s: Source, pcm: bytes, key: str) -> None:
        async with sems[s.name]:
            if cache.get(key, s.name, s.params) is None:
                await pace(s.name)
            h = await s.hypothesis(pcm, key)
        (ok if h is not None else fail)[s.name] += 1

    async def one_agent(pcm: bytes, key: str) -> None:
        async with sem_rt:
            p = await realtime_agent.propose(pcm, key)
        (ok if p is not None else fail)[realtime_agent.NAME] += 1

    async def one_clip(row: dict) -> None:
        nonlocal done
        pcm = read_pcm24k(ROOT / row["path"])
        async with asyncio.TaskGroup() as tg:
            tg.create_task(one_agent(pcm, row["audio_sha"]))
            for s in sources:
                tg.create_task(one_source(s, pcm, row["audio_sha"]))
        done += 1
        rate = done / max(time.monotonic() - t0, 1e-6)
        print(
            f"\r{done}/{len(clips)} clips  {rate:.1f}/s  failures {sum(fail.values())}   ", end="", flush=True
        )

    # Bounded number of clips in flight, so audio is not all loaded at once.
    queue: asyncio.Queue[dict] = asyncio.Queue()
    for r in clips:
        queue.put_nowait(r)

    async def worker() -> None:
        while not queue.empty():
            await one_clip(queue.get_nowait())

    async with asyncio.TaskGroup() as tg:
        for _ in range(args.concurrency):
            tg.create_task(worker())

    print(f"\n{'source':24} {'ok':>6} {'failed':>7}")
    for n in names:
        print(f"{n:24} {ok[n]:6} {fail[n]:7}")
    print(f"cache rows: {cache.count()}")
    if sum(fail.values()):
        print(
            "Some calls failed; re-run to retry transient ones (--retry-errors also retries cached permanent errors)."
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
