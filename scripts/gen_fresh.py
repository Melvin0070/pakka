"""A second batch of prompts and clips, weighted towards confusable values, written to data/fresh/.

The tuning speakers' clips join the tuning data. The test speakers' clips are a locked set: the policy is
frozen before they are scored, and they are scored once. Values are drawn fresh, not reused from
data/prompts.jsonl. Usage: uv run python scripts/gen_fresh.py [--per-speaker 20]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_clips  # noqa: E402
import gen_prompts  # noqa: E402

FRESH = ROOT / "data" / "fresh"
SEED = 20261122
N = 60
# Pairs a listener confuses: -teen/-ty, the "un-" forms one short of a ten, and near-homophones.
TEENS_TENS = [(13, 30), (14, 40), (15, 50), (16, 60), (17, 70), (18, 80), (19, 90)]
UN_FORMS = [19, 29, 39, 49, 59, 69, 79, 89]
NEAR = [(25, 35), (27, 37), (46, 56), (67, 77), (68, 78), (24, 34), (53, 63)]
QUARTERS = [125, 150, 175, 225, 250, 275, 350, 450, 475, 525, 650, 725, 850, 950]


def prompts(seed: int, prefix: str) -> list[dict]:
    rng = random.Random(seed)
    earlier = [ROOT / "data" / "prompts.jsonl", *sorted((ROOT / "data").glob("fresh*/prompts.jsonl"))]
    seen = {
        json.dumps(json.loads(x)["truth"], sort_keys=True)
        for f in earlier
        for x in f.read_text().splitlines()
    }
    out: list[dict] = []

    def when() -> dict:
        x = rng.random()
        if x < 0.4:
            return {"day_of_month": rng.choice([rng.randint(1, 31), *range(13, 20), 30, 31])}
        return {"weekday": rng.choice(gen_prompts.WEEKDAYS)} if x < 0.75 else {}

    def amount(hard: bool) -> int:
        if not hard:
            return rng.choice(QUARTERS) * rng.choice([10, 100, 1000])
        kind = rng.random()
        if kind < 0.35:
            return rng.choice(rng.choice(TEENS_TENS)) * rng.choice([100, 1000])
        if kind < 0.6:
            return rng.choice(UN_FORMS) * rng.choice([100, 1000])
        if kind < 0.85:
            return rng.choice(rng.choice(NEAR)) * rng.choice([100, 1000])
        return rng.choice(QUARTERS) * 1000

    while len(out) < N:
        hard = rng.random() < 0.6
        r = rng.random()
        if r < 0.55:
            truth = {"amount_rupees": amount(hard), **when()}
        elif r < 0.85:
            pool = "7788787801" if hard else "0123456789"
            truth = {"phone": gen_prompts.make_phone(rng, digits_pool=pool, want_repeat=rng.random() < 0.5)}
        else:
            truth = {"phone": gen_prompts.make_phone(rng), "amount_rupees": amount(hard)}
        tag = json.dumps(truth, sort_keys=True)
        if tag in seen:
            continue
        seen.add(tag)
        lang = "en" if rng.random() < 0.17 else "hi"
        out.append(gen_prompts.build(f"{prefix}{len(out) + 1:02d}", truth, rng, lang=lang, hard=hard))
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-speaker", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--batch", type=int, default=1, help="1 writes data/fresh, 2 writes data/fresh2, ...")
    args = ap.parse_args()

    fresh = FRESH if args.batch == 1 else FRESH.with_name(f"fresh{args.batch}")
    seed, prefix = SEED + args.batch - 1, "fghjk"[args.batch - 1]
    fresh.mkdir(parents=True, exist_ok=True)
    path = fresh / "prompts.jsonl"
    if not path.exists():  # never redrawn: the locked set must not move
        path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prompts(seed, prefix)))
    gen_clips.DATA = fresh  # prompts, assignment and manifest for this batch; clips stay under data/clips
    gen_clips.SEED = seed
    batch = gen_clips.load_prompts()
    by_id = {p["id"]: p for p in batch}
    assignment = gen_clips.assign(batch, args.per_speaker)
    (fresh / "assignment.json").write_text(json.dumps(assignment, indent=0) + "\n")

    client = AsyncOpenAI(max_retries=4)
    sem = asyncio.Semaphore(args.concurrency)
    stats = {"made": 0, "skipped": 0, "failed": 0}
    async with asyncio.TaskGroup() as tg:
        for spk, pids in assignment.items():
            for pid in pids:
                tg.create_task(gen_clips.synth(client, sem, spk, by_id[pid], stats))
    print(f"\nclean+phone: {stats}")
    print(f"noisy made: {await asyncio.to_thread(gen_clips.make_noisy, assignment)}")
    print(f"manifest: {gen_clips.write_manifest(batch, assignment)}")
    manifest = fresh / "manifest.jsonl"
    rows = [x for x in manifest.read_text().splitlines() if json.loads(x)["condition"] != "clean"]
    manifest.write_text("\n".join(rows) + "\n")
    n_en = sum(p["lang"] == "en" for p in batch)
    print(
        f"{len(batch)} prompts ({n_en} English, {sum(p['hard'] for p in batch)} confusable), {len(rows)} clips"
    )


if __name__ == "__main__":
    asyncio.run(main())
