"""Write data/human/extras.jsonl: made-up PIN and account lines, and forced-choice questions for people to answer.

Seven items per person for ten people. Never redrawn once written, because recordings are tied to these ids.
Usage: uv run python scripts/gen_human_extras.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from pramaan import confusables, question
from pramaan.lattice import is_valid
from pramaan.lexicon import EN_DIGITS, HI_0_99, WEEKDAYS
from pramaan.types import DIGIT_SLOTS, Slot, SlotDecision, Value, Verdict

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261201
PEOPLE = 10
ANSWER_SLOTS: tuple[Slot, ...] = ("amount_rupees", "phone", "day_of_month", "weekday", "pincode")


def digits_said(digits: str, lang: str) -> str:
    words = [EN_DIGITS[int(d)] if lang == "en" else HI_0_99[int(d)] for d in digits]
    return " ".join(words)


def draw(rng: random.Random, slot: Slot) -> Value:
    if slot == "amount_rupees":
        return rng.choice([125, 175, 225, 275, 350, 450, 650, 850, 1200, 1500, 3600]) * rng.choice([10, 100])
    if slot == "day_of_month":
        return rng.randint(2, 30)
    if slot == "weekday":
        return rng.choice(WEEKDAYS)
    if slot == "phone":
        return rng.choice("6789") + "".join(rng.choices("0123456789", k=9))
    if slot == "pincode":
        return rng.choice("123456789") + "".join(rng.choices("0123456789", k=5))
    return "".join(rng.choices("0123456789", k=rng.choice([11, 12, 14])))


def rival(rng: random.Random, slot: Slot, value: Value) -> Value:
    near = [
        n
        for n in confusables.neighbours(slot, value)
        if n != value
        and is_valid(slot, n)
        and (slot not in DIGIT_SLOTS or len(str(n)) == len(str(value)))
        and (slot != "amount_rupees" or int(n) % 100 == 0)
    ]
    return rng.choice(near)


def indian_grouping(n: int) -> str:
    head, tail = str(n)[:-3], str(n)[-3:]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([*groups, tail])


def meaning(slot: Slot, value: Value) -> str:
    if slot == "amount_rupees":
        return "₹" + indian_grouping(int(value))
    if slot == "day_of_month":
        return f"date {value}"
    if slot == "weekday":
        return str(value).capitalize()
    return " ".join(str(value))


def digit_line(rng: random.Random, pid: str, slot: Slot) -> dict:
    value = draw(rng, slot)
    lang = rng.choice(["hi", "hi", "en"])
    said = digits_said(str(value), lang)
    if slot == "pincode":
        say = f"My PIN code is {said}." if lang == "en" else f"मेरा पिन कोड है {said}।"
    else:
        say = f"My account number is {said}." if lang == "en" else f"मेरा खाता नंबर है {said}।"
    return {
        "id": pid,
        "kind": "digits",
        "say": say,
        "lang": lang,
        "meaning": str(value),
        "truth": {slot: value},
    }


def answer_item(rng: random.Random, pid: str, slot: Slot) -> dict:
    truth = draw(rng, slot)
    options = tuple(question.option_order([truth, rival(rng, slot, truth)]))
    sd = SlotDecision(
        slot=slot, proposed=options[0], verdict=Verdict.ASK, reason="prompt", candidates=options
    )
    return {
        "id": pid,
        "kind": "answer",
        "say": question.phrase(sd),
        "lang": "hi",
        "meaning": meaning(slot, truth),
        "truth": {slot: truth},
        "asked": {"slot": slot, "options": list(options)},
    }


def main() -> None:
    path = ROOT / "data" / "human" / "extras.jsonl"
    if path.exists():
        sys.exit(f"{path} already exists")
    rng = random.Random(SEED)
    rows: list[dict] = []
    for person in range(PEOPLE):
        rows.append(digit_line(rng, f"x{person:02d}p", "pincode"))
        rows.append(digit_line(rng, f"x{person:02d}a", "account_number"))
        rows += [answer_item(rng, f"x{person:02d}q{i}", s) for i, s in enumerate(ANSWER_SLOTS)]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{len(rows)} items for {PEOPLE} people")


if __name__ == "__main__":
    main()
