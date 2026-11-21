"""Synthesise data/clips/{speaker}/{prompt}_{clean,phone,noisy}.wav and write data/manifest.jsonl + data/splits.json.

Each gpt-4o-mini-tts voice with its own speaking-style instructions is one "speaker". Resumable: existing
clips are skipped. Usage: uv run python scripts/gen_clips.py [--per-speaker 50] [--concurrency 8]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import tempfile
from pathlib import Path

import numpy as np
from openai import AsyncOpenAI

from pramaan.audio import (
    RATE,
    add_noise,
    babble,
    phone_amr,
    read_pcm24k,
    sha,
    to_float,
    white_noise,
    write_wav,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CLIPS = DATA / "clips"
SEED = 20261121
SNR_DB = 15.0

# voice -> persona. Accents and delivery vary so that "speaker" means more than a timbre change.
SPEAKERS: dict[str, str] = {
    "alloy": "An Indian caller from Delhi speaking everyday Hinglish at a normal pace, clearly.",
    "ash": "A young man from Mumbai, speaking fast and casually, words running together, like a busy delivery agent.",
    "ballad": "A middle-aged man from eastern Uttar Pradesh with a Bhojpuri accent, relaxed, slightly mumbled.",
    "coral": "A woman from Chennai whose first language is Tamil, speaking Hindi as a second language with a South Indian accent, careful but unsure.",
    "echo": "An older man from Punjab with a Punjabi accent, loud and quick, clipping the ends of words.",
    "fable": "A Bengali speaker from Kolkata speaking Hindi with a Bengali accent, soft vowels, unhurried.",
    "nova": "A college student from Bengaluru, very fast, casual, half-swallowing the numbers, as if on a noisy street.",
    "onyx": "A tired shopkeeper from Indore, low energy, mumbling, speaking quickly to get it over with.",
    "sage": "A woman from Pune with a Marathi accent, polite and moderately paced.",
    "shimmer": "A woman from Hyderabad with a Telugu-influenced Hindi accent, speaking quickly and informally.",
    "verse": "A man from Jaipur with a Rajasthani accent, speaking at a natural conversational pace, a bit nasal.",
    "marin": "An elderly woman from Lucknow speaking slowly but with a weak, breathy voice, slurring some syllables.",
}
TUNE = ["alloy", "ash", "coral", "onyx"]
NOISY = ["ash", "coral", "nova", "verse", "marin"]  # 2 tune + 3 test speakers also get a noisy-phone variant


def load_prompts() -> list[dict]:
    return [json.loads(line) for line in (DATA / "prompts.jsonl").read_text().splitlines() if line.strip()]


def assign(prompts: list[dict], per_speaker: int) -> dict[str, list[str]]:
    """Balanced random assignment: walk a shuffled prompt list cyclically so coverage per prompt is even."""
    rng = random.Random(SEED)
    ids = [p["id"] for p in prompts]
    order = ids[:]
    rng.shuffle(order)
    out: dict[str, list[str]] = {}
    k = 0
    for spk in SPEAKERS:
        chosen: list[str] = []
        while len(chosen) < per_speaker:
            pid = order[k % len(order)]
            k += 1
            if pid not in chosen:
                chosen.append(pid)
        out[spk] = sorted(chosen)
    return out


def clip_path(spk: str, pid: str, cond: str) -> Path:
    return CLIPS / spk / f"{pid}_{cond}.wav"


async def synth(
    client: AsyncOpenAI, sem: asyncio.Semaphore, spk: str, p: dict, stats: dict[str, int]
) -> None:
    clean, phone = clip_path(spk, p["id"], "clean"), clip_path(spk, p["id"], "phone")
    if clean.exists() and phone.exists():
        stats["skipped"] += 1
        return
    async with sem:
        if not clean.exists():
            for attempt in range(4):
                try:
                    r = await client.audio.speech.create(
                        model="gpt-4o-mini-tts",
                        voice=spk,
                        input=p["say"],
                        instructions=SPEAKERS[spk] + " This is a phone call; say exactly the words given.",
                        response_format="pcm",  # raw 24 kHz PCM16 mono
                    )
                    write_wav(clean, r.content, RATE)
                    break
                except Exception as e:
                    if attempt == 3:
                        stats["failed"] += 1
                        print(f"\nTTS failed {spk}/{p['id']}: {e}", file=sys.stderr)
                        return
                    await asyncio.sleep(2 * (attempt + 1))
        await asyncio.to_thread(phone_amr, clean, phone)
        stats["made"] += 1
        print(f"\r{stats}", end="", flush=True)


def make_noisy(assignment: dict[str, list[str]]) -> int:
    made = 0
    talkers: dict[str, list[np.ndarray]] = {}
    for spk in SPEAKERS:
        talkers[spk] = [to_float(read_pcm24k(p)) for p in sorted((CLIPS / spk).glob("*_clean.wav"))[:12]]
    for spk in NOISY:
        others = [t for s, ts in talkers.items() if s != spk for t in ts]
        for pid in assignment[spk]:
            dst = clip_path(spk, pid, "noisy")
            src = clip_path(spk, pid, "clean")
            if dst.exists() or not src.exists():
                continue
            # Seed per clip, so a resumed run makes byte-identical noise.
            rng = np.random.default_rng(int(hashlib.sha256(f"{spk}/{pid}".encode()).hexdigest()[:8], 16))
            pcm = read_pcm24k(src)
            n = len(pcm) // 2
            kind = "babble" if rng.random() < 0.6 else "white"
            noise = babble(n, others, rng) if kind == "babble" else white_noise(n, rng)
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td) / "noisy_clean.wav"
                write_wav(tmp, add_noise(pcm, SNR_DB, noise))
                phone_amr(tmp, dst)
            made += 1
    return made


def write_manifest(prompts: list[dict], assignment: dict[str, list[str]]) -> dict[str, int]:
    by_id = {p["id"]: p for p in prompts}
    rows, counts = [], {"clean": 0, "phone": 0, "noisy": 0}
    for spk, pids in assignment.items():
        for pid in pids:
            for cond in ("clean", "phone", "noisy"):
                path = clip_path(spk, pid, cond)
                if not path.exists():
                    continue
                counts[cond] += 1
                rows.append({
                    "clip_id": f"{spk}_{pid}_{cond}",
                    "speaker": spk,
                    "prompt_id": pid,
                    "condition": cond,
                    "path": str(path.relative_to(ROOT)),
                    "audio_sha": sha(read_pcm24k(path)),
                    "truth": by_id[pid]["truth"],
                })  # fmt: skip
    (DATA / "manifest.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return counts


def write_splits() -> None:
    path = DATA / "splits.json"
    splits = {
        "tune": TUNE,
        "test": [s for s in SPEAKERS if s not in TUNE],
        "note": "Split by speaker, fixed before any results were seen. Never tune on 'test'.",
    }
    if path.exists() and json.loads(path.read_text()) != splits:
        sys.exit("data/splits.json already exists and differs; refusing to move speakers between splits")
    path.write_text(json.dumps(splits, indent=1) + "\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-speaker", type=int, default=50)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    write_splits()
    prompts = load_prompts()
    by_id = {p["id"]: p for p in prompts}
    assignment = assign(prompts, args.per_speaker)
    (DATA / "assignment.json").write_text(json.dumps(assignment, indent=0) + "\n")

    client = AsyncOpenAI(max_retries=2)
    sem = asyncio.Semaphore(args.concurrency)
    stats = {"made": 0, "skipped": 0, "failed": 0}
    async with asyncio.TaskGroup() as tg:
        for spk, pids in assignment.items():
            for pid in pids:
                tg.create_task(synth(client, sem, spk, by_id[pid], stats))
    print(f"\nclean+phone: {stats}")
    print(f"noisy made: {await asyncio.to_thread(make_noisy, assignment)}")
    print(f"manifest: {write_manifest(prompts, assignment)}")


if __name__ == "__main__":
    asyncio.run(main())
