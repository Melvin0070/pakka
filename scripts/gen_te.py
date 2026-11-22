"""Telugu batch: prompts and clips under data/te/, weighted towards values Telugu listeners confuse.

Same voices and the same speaker split as the Hindi data (data/splits.json). The frozen policy was chosen on
Hindi; the tuning speakers' Telugu clips are for developing the Telugu lexicon only, and the test speakers'
clips are scored once. Usage: uv run python scripts/gen_te.py [--per-speaker 20]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

from openai import AsyncOpenAI

from pramaan.lexicon import EN_DIGITS, TE_0_99, TE_SCALE_OBLIQUE, TE_WEEKDAYS, WEEKDAYS
from pramaan.render import _te_fraction_forms, telugu_cardinal, telugu_ordinal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_clips  # noqa: E402
import gen_prompts  # noqa: E402

OUT = ROOT / "data" / "te"
SEED = 20261123
N = 60
# ఇరవై / అరవై, పదిహేను / పదిహేడు, ఎనిమిది / ఎనభై, తొమ్మిది / తొంభై, డెబ్బై / ఎనభై, and English -teen / -ty.
PAIRS = [
    (20, 60),
    (15, 17),
    (8, 80),
    (9, 90),
    (70, 80),
    (16, 60),
    (13, 30),
    (14, 40),
    (12, 20),
    (3, 30),
    (4, 40),
]
QUARTERS = [125, 150, 175, 225, 250, 275, 350, 450, 475, 525, 650, 725, 850, 950]

SPEAKERS: dict[str, str] = {
    "alloy": "A caller from Hyderabad speaking everyday Telugu mixed with English at a normal pace, clearly.",
    "ash": "A young man from Vijayawada speaking Telugu fast and casually, words running together, like a busy delivery agent.",
    "ballad": "A middle-aged farmer from Rayalaseema speaking Telugu with a Rayalaseema accent, relaxed, slightly mumbled.",
    "coral": "A woman from Chennai whose first language is Tamil, speaking Telugu as a second language, careful but unsure.",
    "echo": "An older man from Warangal speaking Telugu with a Telangana accent, loud and quick, clipping the ends of words.",
    "fable": "A Kannada speaker from Bengaluru speaking Telugu with a Kannada accent, soft vowels, unhurried.",
    "nova": "A college student from Hyderabad speaking Telugu very fast, casual, half-swallowing the numbers, as if on a noisy street.",
    "onyx": "A tired shopkeeper from Guntur, low energy, mumbling, speaking Telugu quickly to get it over with.",
    "sage": "A woman from Visakhapatnam speaking Telugu with a coastal Andhra accent, polite and moderately paced.",
    "shimmer": "A woman from the old city of Hyderabad whose Telugu is influenced by Dakhni Urdu, speaking quickly and informally.",
    "verse": "A man from Karimnagar speaking Telugu with a Telangana accent, at a natural conversational pace, a bit nasal.",
    "marin": "An elderly woman from Rajahmundry speaking Telugu slowly with a weak, breathy voice, slurring some syllables.",
}
assert list(SPEAKERS) == list(gen_clips.SPEAKERS)

AMOUNT_FRAMES = [
    "{amt} రూపాయలు {when} ఇచ్చేస్తాను.",
    "{amt} రూపాయల payment {when} అయిపోతుంది.",
    "మొత్తం {amt} రూపాయలు అవుతుంది, {when} transfer చేస్తాను.",
    "{amt} రూపాయల EMI ఉంది, {when} కట్ అవుతుంది.",
    "ఇప్పుడు {amt} రూపాయలు పంపిస్తున్నాను, మిగతాది {when}.",
    "అవునండి, {amt} రూపాయలు {when} పక్కా.",
    "{amt} రూపాయల cheque {when} అందుతుంది.",
    "loan లో {amt} రూపాయలు బాకీ ఉంది, {when} clear చేస్తాను.",
]
AMOUNT_ONLY = [
    "{amt} రూపాయల బిల్లు ఉంది సార్.",
    "{amt} రూపాయలు COD, cash ready గా ఉంచండి.",
    "{amt} రూపాయల recharge చేయండి.",
]
PHONE_FRAMES = [
    "నా నంబర్ నోట్ చేసుకోండి: {ph}.",
    "ఈ నంబర్ కి call చేయండి: {ph}.",
    "callback number {ph}.",
    "{ph}, ఇదే నా whatsapp నంబర్.",
]
PHONE_AMOUNT_FRAME = "{ph} కి phone చేయండి, {amt} రూపాయల గురించి."

TE_DIGIT = {**{d: TE_0_99[d] for d in range(10)}, 0: "జీరో"}  # callers say "zero" in Telugu too


def styles(n: int) -> list[str]:
    out = ["cardinal"]
    if _te_fraction_forms(n, True):
        out += ["fraction"] * 3
    if n % 100 == 0 and n % 1000 and 1100 <= n <= 9900:
        out += ["hundreds"] * 2
    return out


def speak_amount(n: int, style: str) -> str:
    """The shape a number takes before రూపాయలు."""
    if style == "fraction":
        return _te_fraction_forms(n, True)[0]
    if style == "hundreds":
        return f"{TE_0_99[n // 100]} {TE_SCALE_OBLIQUE[100]}"
    if style == "mixed_en":
        return gen_prompts.en_cardinal(n)
    return telugu_cardinal(n, oblique=True)


def speak_phone(digits: str, lang: str, rng: random.Random, multiples: bool) -> str:
    split = rng.choice([(4, 3, 3), (5, 5), (3, 3, 4), (2, 4, 4)])
    groups, i = [], 0
    for k in split:
        groups.append(digits[i : i + k])
        i += k
    spoken = []
    for g in groups:
        gl = rng.choice(["te", "en"]) if lang == "mixed" else lang
        mult = ("double", "triple") if gl == "en" else ("డబుల్", "ట్రిపుల్")
        toks = []
        for ch, k in gen_prompts._runs(g) if multiples else [(c, 1) for c in g]:
            word = EN_DIGITS[int(ch)] if gl == "en" else TE_DIGIT[int(ch)]
            toks.append(word if k == 1 else f"{mult[k - 2]} {word}")
        spoken.append(" ".join(toks))
    return ", ".join(spoken)


def when_phrase(truth: dict, rng: random.Random) -> str:
    if "day_of_month" in truth:
        return f"{telugu_ordinal(truth['day_of_month'])[0]} తేదీన"
    if "weekday" in truth:
        return TE_WEEKDAYS[truth["weekday"]][0] + rng.choice(["", " నాడు"])
    return rng.choice(["ఈరోజు", "రేపు"])


def build(pid: str, truth: dict, rng: random.Random, hard: bool) -> dict:
    fields: dict[str, str] = {}
    style_parts: list[str] = []
    if "amount_rupees" in truth:
        n = truth["amount_rupees"]
        st = "mixed_en" if rng.random() < 0.15 else rng.choice(styles(n))
        fields["amt"] = speak_amount(n, st)
        style_parts.append(f"amount:{st}")
    if "phone" in truth:
        pl = rng.choice(["te", "en", "en", "mixed"])  # most Telugu callers read digits in English
        mult = rng.random() < 0.6
        fields["ph"] = speak_phone(truth["phone"], pl, rng, mult)
        style_parts.append(f"phone:{pl}{'+multiples' if mult else ''}")
    has_when = "day_of_month" in truth or "weekday" in truth
    fields["when"] = when_phrase(truth, rng)
    if "phone" in truth:
        frame = PHONE_AMOUNT_FRAME if "amount_rupees" in truth else rng.choice(PHONE_FRAMES)
    else:
        frame = rng.choice(AMOUNT_FRAMES if has_when else AMOUNT_ONLY)
    return {
        "id": pid,
        "slot_types": sorted(truth),
        "say": frame.format(**fields),
        "truth": truth,
        "rendering_style": ",".join(style_parts),
        "lang": "te",
        "hard": hard,
    }


def prompts() -> list[dict]:
    rng = random.Random(SEED)
    seen: set[str] = set()
    out: list[dict] = []

    def when() -> dict:
        x = rng.random()
        if x < 0.4:
            return {"day_of_month": rng.choice([rng.randint(1, 31), *range(13, 21), 30, 31])}
        return {"weekday": rng.choice(WEEKDAYS)} if x < 0.75 else {}

    def amount(hard: bool) -> int:
        if hard and rng.random() < 0.7:
            return rng.choice(rng.choice(PAIRS)) * rng.choice([100, 1000, 1000])
        return rng.choice(QUARTERS) * rng.choice([10, 100, 1000])

    while len(out) < N:
        hard = rng.random() < 0.6
        r = rng.random()
        if r < 0.55:
            truth = {"amount_rupees": amount(hard), **when()}
        elif r < 0.85:
            pool = "6677678601" if hard else "0123456789"  # ఆరు / ఏడు, six / seven
            truth = {"phone": gen_prompts.make_phone(rng, digits_pool=pool, want_repeat=rng.random() < 0.5)}
        else:
            truth = {"phone": gen_prompts.make_phone(rng), "amount_rupees": amount(hard)}
        tag = json.dumps(truth, sort_keys=True)
        if tag in seen:
            continue
        seen.add(tag)
        out.append(build(f"te{len(out) + 1:02d}", truth, rng, hard))
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-speaker", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--prompts-only", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "prompts.jsonl"
    if not path.exists():  # never redrawn once clips exist
        path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prompts()))
    if args.prompts_only:
        return
    gen_clips.DATA, gen_clips.SEED, gen_clips.SPEAKERS = OUT, SEED, SPEAKERS
    batch = gen_clips.load_prompts()
    by_id = {p["id"]: p for p in batch}
    assignment = gen_clips.assign(batch, args.per_speaker)
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
    print(f"manifest: {gen_clips.write_manifest(batch, assignment)}")
    manifest = OUT / "manifest.jsonl"
    rows = [x for x in manifest.read_text().splitlines() if json.loads(x)["condition"] != "clean"]
    manifest.write_text("\n".join(rows) + "\n")
    print(f"{len(batch)} prompts ({sum(p['hard'] for p in batch)} confusable), {len(rows)} clips")


if __name__ == "__main__":
    asyncio.run(main())
