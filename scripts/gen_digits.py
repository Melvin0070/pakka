"""PIN code and account number lines for the test speakers, written to data/digits/.

The first three sets hold amounts, dates and phone numbers only. This one measures the two digit types added
later, on the same test voices and phone channel, under the policy frozen before either type existed. Nothing
is tuned on it: the tuning speakers do not speak these lines. Usage: make digits-data (spends API credits)
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

OUT = ROOT / "data" / "digits"
SEED = 20261123
N = 40
# The last frame of each list puts words between the label and the digits, which the parser's label rule
# does not accept. It stays in: a caller says it that way, and the set should show what that costs.
FRAMES = {
    ("pincode", "hi"): ["मेरा पिन कोड है {d}।", "पिन कोड {d} है।", "पिन कोड नोट कीजिए, {d}।"],
    ("pincode", "en"): ["My PIN code is {d}.", "The PIN code is {d}.", "Please note the PIN code, {d}."],
    ("account_number", "hi"): ["मेरा खाता नंबर है {d}।", "अकाउंट नंबर {d} है।", "खाता नंबर नोट कीजिए, {d}।"],
    ("account_number", "en"): [
        "My account number is {d}.",
        "Account number {d}.",
        "Please note my account number, {d}.",
    ],
}
WORDS = {"hi": gen_prompts.HI_DIGIT, "en_dev": gen_prompts.EN_DIGITS_DEV, "en": gen_prompts.EN_DIGITS}


def draw(rng: random.Random, slot: str, hard: bool) -> str:
    # Hard: a small pool, so the number is full of repeats and of the digits most often swapped.
    pool = "7788660011" if hard else "0123456789"
    if slot == "pincode":
        return rng.choice("123456789") + "".join(rng.choice(pool) for _ in range(5))
    return "".join(rng.choice(pool) for _ in range(rng.choice([9, 11, 12, 14, 16])))


def speak(digits: str, style: str, rng: random.Random, multiples: bool) -> str:
    """Groups of two to four digits with a pause between; 'mixed' picks Hindi or English words per group."""
    groups, i = [], 0
    while i < len(digits):
        k = min(rng.choice([2, 3, 3, 4]), len(digits) - i)
        groups.append(digits[i : i + k])
        i += k
    spoken = []
    for g in groups:
        s = rng.choice(["hi", "en_dev"]) if style == "mixed" else style
        double = ("double", "triple") if s == "en" else ("डबल", "ट्रिपल")
        runs = gen_prompts._runs(g) if multiples else [(c, 1) for c in g]
        spoken.append(
            " ".join(WORDS[s][int(c)] if k == 1 else f"{double[k - 2]} {WORDS[s][int(c)]}" for c, k in runs)
        )
    return ", ".join(spoken)


def prompts() -> list[dict]:
    rng = random.Random(SEED)
    out: list[dict] = []
    for i in range(N):
        slot = "pincode" if i % 2 == 0 else "account_number"
        hard = rng.random() < 0.5
        lang = "en" if rng.random() < 0.25 else "hi"
        style = "en" if lang == "en" else rng.choice(["hi", "hi", "en_dev", "mixed"])
        multiples = rng.random() < 0.4
        value = draw(rng, slot, hard)
        frames = FRAMES[slot, lang]
        frame = frames[2] if rng.random() < 0.2 else rng.choice(frames[:2])
        out.append(
            {
                "id": f"d{i + 1:02d}",
                "kind": "digits",
                "say": frame.format(d=speak(value, style, rng, multiples)),
                "lang": lang,
                "hard": hard,
                "style": f"{slot}:{style}{'+multiples' if multiples else ''}",
                "label_adjacent": frame != frames[2],
                "truth": {slot: value},
            }
        )
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-speaker", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "prompts.jsonl"
    if not path.exists():  # never redrawn: the clips and the cached responses are tied to these lines
        path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prompts()))
    gen_clips.DATA, gen_clips.SEED = OUT, SEED  # clips still go under data/clips
    batch = gen_clips.load_prompts()
    by_id = {p["id"]: p for p in batch}
    assignment = {
        spk: [] if spk in gen_clips.TUNE else pids
        for spk, pids in gen_clips.assign(batch, args.per_speaker).items()
    }
    (OUT / "assignment.json").write_text(json.dumps(assignment, indent=0) + "\n")

    client = AsyncOpenAI(max_retries=4)
    sem = asyncio.Semaphore(args.concurrency)
    stats = {"made": 0, "skipped": 0, "failed": 0}
    async with asyncio.TaskGroup() as tg:
        for spk, pids in assignment.items():
            for pid in pids:
                tg.create_task(gen_clips.synth(client, sem, spk, by_id[pid], stats))
    print(f"\nclean+phone: {stats}")
    print(f"noisy made: {await asyncio.to_thread(gen_clips.make_noisy, assignment)}")
    gen_clips.write_manifest(batch, assignment)
    manifest = OUT / "manifest.jsonl"
    rows = [json.loads(x) for x in manifest.read_text().splitlines()]
    rows = [{**r, "kind": "digits"} for r in rows if r["condition"] != "clean"]
    manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{len(batch)} prompts, {len(rows)} clips from {len({r['speaker'] for r in rows})} speakers")


if __name__ == "__main__":
    asyncio.run(main())
