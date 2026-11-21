"""One short forced-choice question in Roman Hinglish that the agent can speak. Pure and deterministic."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .types import Slot, SlotDecision, Value, Verdict

ROMAN_0_99: tuple[str, ...] = (
    "shunya", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat", "aath", "nau",
    "das", "gyaarah", "baarah", "terah", "chaudah", "pandrah", "solah", "satrah", "athaarah", "unnees",
    "bees", "ikkees", "baaees", "teis", "chaubees", "pachchees", "chhabbees", "sattaais", "atthaais", "untees",
    "tees", "iktees", "battees", "taintees", "chauntees", "paintees", "chhattees", "saintees", "adtees", "untaalees",
    "chaalees", "iktaalees", "bayaalees", "taintaalees", "chauvaalees", "paintaalees", "chhiyaalees", "saintaalees",
    "adtaalees", "unchaas",
    "pachaas", "ikyaavan", "baavan", "tirpan", "chauvan", "pachpan", "chhappan", "sattaavan", "atthaavan", "unsath",
    "saath", "iksath", "baasath", "tirsath", "chaunsath", "painsath", "chhiyaasath", "sadsath", "adsath", "unhattar",
    "sattar", "ikhattar", "bahattar", "tihattar", "chauhattar", "pachhattar", "chhihattar", "sathattar", "athhattar",
    "unaasi",
    "assi", "ikyaasi", "bayaasi", "tiraasi", "chauraasi", "pachaasi", "chhiyaasi", "sattaasi", "atthaasi", "navaasi",
    "nabbe", "ikyaanve", "baanve", "tiraanve", "chauraanve", "pachaanve", "chhiyaanve", "sattaanve", "atthaanve",
    "ninyaanve",
)  # fmt: skip
assert len(ROMAN_0_99) == 100

_SCALES = ((10_000_000, "crore"), (100_000, "lakh"), (1000, "hazaar"), (100, "sau"))
ROMAN_WEEKDAYS = {
    "monday": "somvaar", "tuesday": "mangalvaar", "wednesday": "budhvaar", "thursday": "guruvaar",
    "friday": "shukravaar", "saturday": "shanivaar", "sunday": "ravivaar",
}  # fmt: skip
_ORDINALS = (
    "pehla",
    "doosra",
    "teesra",
    "chautha",
    "paanchvaan",
    "chhatha",
    "saatvaan",
    "aathvaan",
    "nauvaan",
    "dasvaan",
)
_REPEAT = {
    "amount_rupees": "Maaf kijiye, amount ek baar phir se boliye?",
    "day_of_month": "Maaf kijiye, taarikh ek baar phir se boliye?",
    "weekday": "Maaf kijiye, din ek baar phir se boliye?",
    "phone": "Maaf kijiye, number ek baar phir se dheere boliye?",
}


def roman_cardinal(n: int) -> str:
    if not 0 <= n < 1_000_000_000:
        raise ValueError(n)
    if n < 100:
        return ROMAN_0_99[n]
    parts: list[str] = []
    for unit, word in _SCALES:
        k, n = divmod(n, unit)
        if k:
            parts.append(f"{roman_cardinal(k)} {word}")
    if n:
        parts.append(ROMAN_0_99[n])
    return " ".join(parts)


def roman_digits(digits: str) -> str:
    words = [ROMAN_0_99[int(d)] for d in digits]
    if len(words) == 10:
        return " ".join(words[:5]) + ", " + " ".join(words[5:])
    return " ".join(words)


def say(slot: Slot, value: Value) -> str:
    if slot == "amount_rupees":
        return roman_cardinal(int(value))
    if slot == "day_of_month":
        return f"{roman_cardinal(int(value))} taarikh"
    if slot == "weekday":
        return ROMAN_WEEKDAYS.get(str(value), str(value))
    if slot == "phone":
        return roman_digits(str(value))
    raise ValueError(slot)


def option_order(options: Sequence[Value]) -> list[Value]:
    """Order seeded by the option set itself: not always best-first (which would lead the caller), yet replayable."""
    seed = "|".join(sorted(str(o) for o in options))
    return sorted(options, key=lambda o: hashlib.sha256(f"{seed}#{o}".encode()).hexdigest())


def position_phrase(i: int, length: int = 10) -> str:
    from_end = length - i
    if from_end == 1:
        return "aakhri ank"
    if i < length // 2:
        return f"{_ORDINALS[i]} ank"
    return f"aakhri se {_ORDINALS[from_end - 1]} ank"


def _choice(parts: Sequence[str]) -> str:
    if len(parts) == 2:
        return f"{parts[0]}, ya {parts[1]}?"
    return ", ".join(parts[:-1]) + f", ya {parts[-1]}?"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def repeat(slot: Slot) -> str:
    return _REPEAT[slot]


def phrase(sd: SlotDecision) -> str:
    """ASK: forced choice over the decision's candidates (at most three). Otherwise a request to repeat."""
    options = list(sd.candidates[:3])
    if sd.verdict != Verdict.ASK or len(options) < 2:
        return repeat(sd.slot)
    ordered = option_order(options)
    if sd.slot == "phone":
        strs = [str(o) for o in ordered]
        if len({len(s) for s in strs}) == 1:
            diff = [i for i in range(len(strs[0])) if len({s[i] for s in strs}) > 1]
            if len(diff) == 1:
                i = diff[0]
                digits = [ROMAN_0_99[int(s[i])] for s in strs]
                if len(digits) == 2:
                    return _cap(f"{position_phrase(i, len(strs[0]))} {digits[0]} hai ya {digits[1]}?")
                return _cap(f"{position_phrase(i, len(strs[0]))} " + _choice(digits))
        return _cap("number " + _choice([say("phone", o) for o in ordered]))
    return _cap(_choice([say(sd.slot, o) for o in ordered]))
