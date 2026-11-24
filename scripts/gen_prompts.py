"""Generate data/prompts.jsonl: what synthetic callers say, with exact typed truth.

Spoken numbers come from pakka.render / lexicon, so the sentence says exactly the truth value.
Deterministic (fixed seed); re-running rewrites the same file.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pakka.lexicon import EN_DIGITS, EN_DIGITS_DEV, HI_0_99, HI_WEEKDAYS, WEEKDAYS
from pakka.render import amount_renderings, hindi_cardinal

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "prompts.jsonl"
SEED = 20261121

EN_0_19 = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen"
).split()
EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
EN_ORD = {
    1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth", 9: "ninth", 12: "twelfth",
    20: "twentieth", 30: "thirtieth",
}  # fmt: skip


def en_cardinal(n: int) -> str:
    """Indian-English: lakh, not hundred thousand."""
    if n < 20:
        return EN_0_19[n]
    if n < 100:
        t, u = divmod(n, 10)
        return EN_TENS[t] + (f"-{EN_0_19[u]}" if u else "")
    parts: list[str] = []
    for unit, word in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "thousand"), (100, "hundred")):
        k, n = divmod(n, unit)
        if k:
            parts.append(f"{en_cardinal(k)} {word}")
    if n:
        parts.append(en_cardinal(n))
    return " ".join(parts)


def en_ordinal(n: int) -> str:
    if n in EN_ORD:
        return EN_ORD[n]
    if n < 20:
        return en_cardinal(n) + "th"
    t, u = divmod(n, 10)
    if u == 0:
        return EN_TENS[t][:-1] + "ieth"
    return f"{EN_TENS[t]}-{EN_ORD.get(u) or en_cardinal(u) + 'th'}"


def en_amount(n: int, rng: random.Random) -> tuple[str, str]:
    # "thirteen hundred" for round hundreds 1100-9900 that are not round thousands, as Indians often say.
    if n % 100 == 0 and n % 1000 and 1100 <= n <= 9900 and rng.random() < 0.6:
        return f"{en_cardinal(n // 100)} hundred", "en_hundreds"
    return en_cardinal(n), "en_cardinal"


def hi_amount(n: int, style: str) -> str:
    forms = amount_renderings(n)
    if style == "cardinal":
        return hindi_cardinal(n)
    if style == "sau":
        return next(f for f in forms if f.endswith("सौ") and len(f.split()) == 2 and f != hindi_cardinal(n))
    if style == "fraction":
        return next(f for f in forms[1:] if f.split()[0] in ("सवा", "साढ़े", "पौने", "डेढ़", "ढाई"))
    raise ValueError(style)


def best_hi_style(n: int, rng: random.Random) -> str:
    forms = amount_renderings(n)
    styles = ["cardinal"]
    if any(f.split()[0] in ("सवा", "साढ़े", "पौने", "डेढ़", "ढाई") for f in forms[1:]):
        styles += ["fraction"] * 3
    if any(f.endswith("सौ") and len(f.split()) == 2 and f != hindi_cardinal(n) for f in forms):
        styles += ["sau"] * 2
    return rng.choice(styles)


# ---- phone numbers -----------------------------------------------------------------------------------------

HI_DIGIT = {**{d: HI_0_99[d] for d in range(10)}, 0: "ज़ीरो"}  # callers say "zero" even in Hindi


def _runs(group: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for ch in group:
        if out and out[-1][0] == ch and out[-1][1] < 3:
            out[-1] = (ch, out[-1][1] + 1)
        else:
            out.append((ch, 1))
    return out


def speak_phone(digits: str, lang: str, rng: random.Random, use_multiples: bool) -> str:
    """lang: 'hi' Hindi digits, 'en_dev' English digits in Devanagari, 'en' English digits (Latin),
    'mixed' per-group choice of hi/en_dev. Grouping 4-3-3, 5-5 or 3-3-4 with commas."""
    split = rng.choice([(4, 3, 3), (5, 5), (3, 3, 4), (2, 4, 4)])
    groups, i = [], 0
    for k in split:
        groups.append(digits[i : i + k])
        i += k
    spoken = []
    for g in groups:
        gl = rng.choice(["hi", "en_dev"]) if lang == "mixed" else lang
        word = {
            "hi": lambda d: HI_DIGIT[d],
            "en_dev": lambda d: EN_DIGITS_DEV[d],
            "en": lambda d: EN_DIGITS[d],
        }[gl]
        mult = {"en": ("double", "triple")}.get(gl, ("डबल", "ट्रिपल"))
        toks = []
        for ch, k in _runs(g) if use_multiples else [(c, 1) for c in g]:
            d = int(ch)
            if k == 1:
                toks.append(word(d))
            else:
                toks.append(f"{mult[k - 2]} {word(d)}")
        spoken.append(" ".join(toks))
    return ", ".join(spoken)


def make_phone(rng: random.Random, digits_pool: str = "0123456789", want_repeat: bool = False) -> str:
    while True:
        p = rng.choice("6789") + "".join(rng.choice(digits_pool) for _ in range(9))
        if not want_repeat:
            return p
        if any(p[i] == p[i + 1] for i in range(9)):
            return p


# ---- sentence frames ----------------------------------------------------------------------------------------

HI_AMOUNT_FRAMES = [
    "{amt} रुपये {when} दे दूँगा।",
    "{amt} का payment {when} हो जाएगा।",
    "total {amt} बनता है, {when} transfer करूँगा।",
    "{amt} का EMI है, {when} कटेगा।",
    "अभी {amt} भेज रहा हूँ, बाकी {when}।",
    "हाँ जी, {amt} रुपये {when} पक्का।",
    "{amt} का cheque {when} मिलेगा।",
    "loan का {amt} बाकी है, {when} clear कर दूँगा।",
]
HI_AMOUNT_ONLY = ["{amt} रुपये का बिल है सर।", "{amt} रुपये COD है, cash ready रखना।", "{amt} का recharge कर दो।"]
HI_PHONE_FRAMES = [
    "मेरा नंबर नोट करो: {ph}।",
    "इस नंबर पे call करना: {ph}।",
    "callback number है {ph}।",
    "{ph}, यही मेरा whatsapp नंबर है।",
]
HI_PHONE_PLUS_FRAMES = ["{ph} पे phone करो, {amt} के बारे में।", "{ph} पे {when} call करना।"]
EN_FRAMES = [
    "I will pay {amt} rupees {when}.",
    "The amount is {amt}, I'll transfer it {when}.",
    "Please note, {amt} rupees, payment {when}.",
]
EN_PHONE_FRAMES = ["My number is {ph}.", "Call me back on {ph}.", "Note my number, {ph}."]


def hi_when(slots: dict, rng: random.Random) -> str:
    if "day_of_month" in slots:
        return f"{HI_0_99[slots['day_of_month']]} तारीख को"
    if "weekday" in slots:
        return f"{rng.choice(HI_WEEKDAYS[slots['weekday']])} को"
    return rng.choice(["आज", "कल"])


def en_when(slots: dict) -> str:
    if "day_of_month" in slots:
        return f"on the {en_ordinal(slots['day_of_month'])}"
    if "weekday" in slots:
        return f"on {slots['weekday'].capitalize()}"
    return "today"


def build(pid: str, truth: dict, rng: random.Random, lang: str = "hi", amount_style: str | None = None,
          phone_lang: str | None = None, hard: bool = False, multiples: bool | None = None) -> dict:  # fmt: skip
    style_parts: list[str] = []
    when_slots = {k: v for k, v in truth.items() if k in ("day_of_month", "weekday")}
    fields: dict[str, str] = {}
    if "amount_rupees" in truth:
        n = truth["amount_rupees"]
        if lang == "en":
            fields["amt"], st = en_amount(n, rng)
        elif amount_style == "mixed_en":
            fields["amt"], st = en_cardinal(n), "mixed_en"
        else:
            st = amount_style or best_hi_style(n, rng)
            fields["amt"] = hi_amount(n, st)
        style_parts.append(f"amount:{st}")
    if "phone" in truth:
        pl = "en" if lang == "en" else (phone_lang or rng.choice(["hi", "en_dev", "mixed"]))
        mult = rng.random() < 0.6 if multiples is None else multiples
        fields["ph"] = speak_phone(truth["phone"], pl, rng, mult)
        style_parts.append(f"phone:{pl}{'+multiples' if mult else ''}")
    if lang == "en":
        fields["when"] = en_when(when_slots)
        if "phone" in truth and len(truth) > 1:
            frame = (
                "Call me on {ph} about the {amt} rupees."
                if "amount_rupees" in truth
                else "Call me on {ph} {when}."
            )
        elif "phone" in truth:
            frame = rng.choice(EN_PHONE_FRAMES)
        else:
            frame = rng.choice(EN_FRAMES)
    else:
        fields["when"] = hi_when(when_slots, rng)
        if "phone" in truth and len(truth) > 1:
            frame = HI_PHONE_PLUS_FRAMES[0] if "amount_rupees" in truth else HI_PHONE_PLUS_FRAMES[1]
        elif "phone" in truth:
            frame = rng.choice(HI_PHONE_FRAMES)
        elif when_slots:
            frame = rng.choice(HI_AMOUNT_FRAMES)
        else:
            frame = rng.choice(HI_AMOUNT_ONLY)
    say = frame.format(**fields)
    if when_slots:
        k = next(iter(when_slots))
        style_parts.append(f"{k}:{'en' if lang == 'en' else 'hi'}")
    slot_types = sorted(truth)
    return {
        "id": pid,
        "slot_types": slot_types,
        "say": say,
        "truth": truth,
        "rendering_style": ",".join(style_parts),
        "lang": lang,
        "hard": hard,
    }


# g0 values, with the amount style each original sentence used.
G0 = [
    ("a01", {"amount_rupees": 2750, "weekday": "tuesday"}, "fraction"),
    ("a02", {"amount_rupees": 225000, "day_of_month": 25}, "fraction"),
    ("a03", {"amount_rupees": 2500, "weekday": "friday"}, "fraction"),
    ("a04", {"amount_rupees": 150000, "day_of_month": 21}, "fraction"),
    ("a05", {"amount_rupees": 750}, "fraction"),
    ("a06", {"amount_rupees": 5500, "weekday": "monday"}, "sau"),
    ("a07", {"amount_rupees": 19500, "day_of_month": 3}, "cardinal"),
    ("a08", {"amount_rupees": 39000, "weekday": "wednesday"}, "cardinal"),
    ("a09", {"amount_rupees": 59000, "weekday": "thursday"}, "cardinal"),
    ("a10", {"amount_rupees": 15000, "day_of_month": 15}, "en"),
    ("a11", {"amount_rupees": 50000, "day_of_month": 17}, "mixed_en"),
    ("a12", {"amount_rupees": 17000, "weekday": "saturday"}, "cardinal"),
    ("a13", {"amount_rupees": 70000, "day_of_month": 27}, "cardinal"),
    ("a14", {"amount_rupees": 12500}, "fraction"),
    ("a15", {"amount_rupees": 175}, "fraction"),
    ("a16", {"amount_rupees": 325, "weekday": "sunday"}, "fraction"),
    ("a17", {"amount_rupees": 120000, "day_of_month": 29}, "cardinal"),
    ("a18", {"amount_rupees": 7500, "weekday": "tuesday"}, "sau"),
    ("a19", {"amount_rupees": 3330}, "cardinal"),
    ("a20", {"amount_rupees": 94000, "day_of_month": 19}, "cardinal"),
    ("a21", {"amount_rupees": 9999}, "cardinal"),
    ("a22", {"amount_rupees": 1300, "day_of_month": 30}, "en"),
    ("a23", {"amount_rupees": 250000, "weekday": "wednesday"}, "fraction"),
    ("a24", {"amount_rupees": 6660, "day_of_month": 26}, "cardinal"),
    ("p01", {"phone": "9844712000"}, "en"),
    ("p02", {"phone": "7092334156"}, "hi"),
    ("p03", {"phone": "9986051227"}, "mixed"),
    ("p04", {"phone": "8311907654", "amount_rupees": 4500}, "hi"),
    ("p05", {"phone": "6300198472"}, "en"),
    ("p06", {"phone": "9411182730", "weekday": "friday"}, "hi"),
]


def main() -> None:
    rng = random.Random(SEED)
    prompts: list[dict] = []

    for pid, truth, st in G0:
        if st == "en":
            prompts.append(build(f"g0_{pid}", truth, rng, lang="en", multiples=True))
        elif "phone" in truth:
            prompts.append(build(f"g0_{pid}", truth, rng, phone_lang=st, multiples=True))
        else:
            prompts.append(build(f"g0_{pid}", truth, rng, amount_style=st))

    def when(r: random.Random) -> dict:
        x = r.random()
        if x < 0.4:
            return {"day_of_month": r.randint(1, 31)}
        if x < 0.75:
            return {"weekday": r.choice(WEEKDAYS)}
        return {}

    # Confusable-numeral hard set.
    hard: list[dict] = []
    for t in (29, 39, 49, 59, 69, 79, 89):
        hard.append({"amount_rupees": t * 1000, **when(rng)})
    for a, b in ((17, 70), (15, 50), (13, 30), (16, 60), (25, 35), (35, 45), (67, 77), (96, 99)):
        hard.append(
            {
                "amount_rupees": a * 1000,
                "day_of_month": rng.choice([d for d in (a, b) if d <= 31] or [rng.randint(1, 31)]),
            }
        )
        hard.append({"amount_rupees": b * 1000, **when(rng)})
        if a <= 31 and b <= 31:
            hard.append({"amount_rupees": rng.choice([500, 1200, 2000, 8000]), "day_of_month": b})
    for x in (13, 15, 16, 17):  # "satrah sau" style, a trap next to the "sattar hazaar" amounts above
        hard.append({"amount_rupees": x * 100, **when(rng)})
    for _ in range(6):  # 7 vs 8 digit-dense phones (saat / aath)
        hard.append({"phone": make_phone(rng, digits_pool="7788787801")})
    en_traps = {13_000, 15_000, 16_000, 17_000, 30_000, 50_000, 60_000, 70_000}  # teen/ty: the English trap
    for i, truth in enumerate(hard):
        amt = truth.get("amount_rupees")
        lang = "en" if (amt in en_traps and rng.random() < 0.5) or rng.random() < 0.1 else "hi"
        style = None
        if lang == "hi" and amt is not None:
            style = "sau" if amt in (1300, 1500, 1600, 1700) else ("cardinal" if rng.random() < 0.7 else None)
        prompts.append(build(f"h{i + 1:02d}", truth, rng, lang=lang, amount_style=style, hard=True))

    # General coverage to reach ~120.
    general_amounts = [
        250, 450, 1250, 1750, 2250, 3500, 4750, 6500, 8250, 11000, 23500, 42000, 64000, 81000,
        125000, 175000, 350000, 425000, 1200000, 875, 1500, 99000, 5600, 7800,
    ]  # fmt: skip
    i = 0
    while len(prompts) < 114:
        i += 1
        r = rng.random()
        if r < 0.55:
            truth = {"amount_rupees": general_amounts[i % len(general_amounts)], **when(rng)}
        elif r < 0.8:
            truth = {"phone": make_phone(rng, want_repeat=rng.random() < 0.5)}
        elif r < 0.9:
            truth = {"phone": make_phone(rng), "amount_rupees": rng.choice([1500, 2500, 4500, 12000])}
        else:
            truth = {"phone": make_phone(rng), "weekday": rng.choice(WEEKDAYS)}
        lang = "en" if rng.random() < 0.15 else "hi"
        style = "mixed_en" if lang == "hi" and "amount_rupees" in truth and rng.random() < 0.1 else None
        prompts.append(build(f"n{i:02d}", truth, rng, lang=lang, amount_style=style))

    # Fill to 120, topping the English share up to ~15%.
    j = 0
    while len(prompts) < 120:
        j += 1
        truth = (
            {"amount_rupees": rng.choice(general_amounts), **when(rng)}
            if j % 2
            else {"phone": make_phone(rng, want_repeat=True)}
        )
        lang = "en" if sum(p["lang"] == "en" for p in prompts) < 18 else "hi"
        prompts.append(build(f"e{j:02d}", truth, rng, lang=lang))

    ids = [p["id"] for p in prompts]
    assert len(ids) == len(set(ids))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prompts))
    n_en = sum(p["lang"] == "en" for p in prompts)
    n_hard = sum(p["hard"] for p in prompts)
    print(f"{len(prompts)} prompts ({n_en} English, {n_hard} hard) -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
