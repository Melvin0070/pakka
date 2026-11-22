"""One short forced-choice question the agent can speak: Roman Hinglish, or Telugu. Pure and deterministic."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from .lattice import canon
from .lexicon import TE_0_99, TE_WEEKDAYS
from .normalise import small_numbers
from .render import telugu_cardinal, telugu_ordinal
from .types import DIGIT_SLOTS, Slot, SlotDecision, Value, Verdict

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
    "pincode": "Maaf kijiye, PIN code ek baar phir se dheere boliye?",
    "account_number": "Maaf kijiye, account number ek baar phir se dheere boliye?",
}
# Bare पहले and "second" are everyday words ("earlier", "one second"), so they need a "wala" or "the".
_WALA = r"\s*(?:wala|wali|wale|वाला|वाली|वाले)"
_PICK_ORDINAL = (
    re.compile(rf"(?<!\w)(?:pehla|pahla|पहला|पहली|(?:pehle|pahle|पहले){_WALA}|the\s+first|first\s+(?:one|option))(?!\w)", re.I),
    re.compile(rf"(?<!\w)(?:doosra|dusra|दूसरा|दूसरी|(?:doosre|dusre|दूसरे){_WALA}|the\s+second|second\s+(?:one|option))(?!\w)", re.I),
    re.compile(rf"(?<!\w)(?:teesra|tisra|तीसरा|तीसरी|(?:teesre|tisre|तीसरे){_WALA}|the\s+third|third\s+(?:one|option))(?!\w)", re.I),
)  # fmt: skip
_PICK_ORDINAL_TE = tuple(
    re.compile(rf"(?<!\w)(?:{words})", re.I)
    for words in ("మొదటి|ఫస్ట్|modati", "రెండో|రెండవ|సెకండ్|rendo", "మూడో|మూడవ|థర్డ్|moodo")
)
_REPEAT_TE = {
    "amount_rupees": "క్షమించండి, amount మరోసారి చెప్తారా?",
    "day_of_month": "క్షమించండి, తేదీ మరోసారి చెప్తారా?",
    "weekday": "క్షమించండి, ఏ రోజో మరోసారి చెప్తారా?",
    "phone": "క్షమించండి, నంబర్ మరోసారి నెమ్మదిగా చెప్తారా?",
    "pincode": "క్షమించండి, PIN code మరోసారి నెమ్మదిగా చెప్తారా?",
    "account_number": "క్షమించండి, account number మరోసారి నెమ్మదిగా చెప్తారా?",
}
_ORDINALS_TE = ("మొదటి", "రెండో", "మూడో", "నాలుగో", "ఐదో", "ఆరో", "ఏడో", "ఎనిమిదో", "తొమ్మిదో", "పదో")
_AMOUNT_UNITS = (100, 1000, 100_000, 10_000_000)
MAX_SPOKEN_OPTIONS = 3


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
    if slot in DIGIT_SLOTS:
        return roman_digits(str(value))
    raise ValueError(slot)


def say_te(slot: Slot, value: Value) -> str:
    if slot == "amount_rupees":
        return f"{telugu_cardinal(int(value), oblique=True)} రూపాయలు"
    if slot == "day_of_month":
        return f"{telugu_ordinal(int(value))[0]} తేదీ"
    if slot == "weekday":
        return TE_WEEKDAYS[str(value)][0] if str(value) in TE_WEEKDAYS else str(value)
    if slot in DIGIT_SLOTS:
        words = [TE_0_99[int(d)] for d in str(value)]
        half = len(words) // 2
        return " ".join(words[:half]) + ", " + " ".join(words[half:]) if len(words) == 10 else " ".join(words)
    raise ValueError(slot)


def _phrase_te(sd: SlotDecision, ordered: Sequence[Value]) -> str:
    if sd.slot in DIGIT_SLOTS:
        strs = [str(o) for o in ordered]
        if len({len(s) for s in strs}) == 1:
            diff = [i for i in range(len(strs[0])) if len({s[i] for s in strs}) > 1]
            if len(diff) == 1:
                i, n = diff[0], len(strs[0])
                where = "చివరి అంకె" if n - i == 1 else (
                    f"{_ORDINALS_TE[i]} అంకె" if i < n // 2 else f"చివరి నుంచి {_ORDINALS_TE[n - i - 1]} అంకె"
                )  # fmt: skip
                return f"{where} " + ", లేదా ".join(TE_0_99[int(s[i])] for s in strs) + "?"
    return ", లేదా ".join(say_te(sd.slot, o) for o in ordered) + "?"


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


def repeat(slot: Slot, lang: str = "hi") -> str:
    return (_REPEAT_TE if lang == "te" else _REPEAT)[slot]


def phrase(sd: SlotDecision, lang: str = "hi") -> str:
    """ASK: forced choice over the decision's candidates (at most three). Otherwise a request to repeat."""
    options = list(sd.candidates[:MAX_SPOKEN_OPTIONS])
    if sd.verdict != Verdict.ASK or len(options) < 2:
        return repeat(sd.slot, lang)
    ordered = option_order(options)
    if lang == "te":
        return _phrase_te(sd, ordered)
    if sd.slot in DIGIT_SLOTS:
        strs = [str(o) for o in ordered]
        if len({len(s) for s in strs}) == 1:
            diff = [i for i in range(len(strs[0])) if len({s[i] for s in strs}) > 1]
            if len(diff) == 1:
                i = diff[0]
                digits = [ROMAN_0_99[int(s[i])] for s in strs]
                if len(digits) == 2:
                    return _cap(f"{position_phrase(i, len(strs[0]))} {digits[0]} hai ya {digits[1]}?")
                return _cap(f"{position_phrase(i, len(strs[0]))} " + _choice(digits))
        return _cap("number " + _choice([say(sd.slot, o) for o in ordered]))
    return _cap(_choice([say(sd.slot, o) for o in ordered]))


def _short_matches(slot: Slot, options: Sequence[Value], numbers: Sequence[int]) -> set[Value]:
    if slot in DIGIT_SLOTS:
        strs = [str(o) for o in options]
        if len({len(s) for s in strs}) != 1:
            return set()
        diff = [i for i in range(len(strs[0])) if len({s[i] for s in strs}) > 1]
        if len(diff) != 1:
            return set()
        said = {str(n) for n in numbers if n < 10}
        return {o for o, s in zip(options, strs, strict=True) if s[diff[0]] in said}
    if slot == "day_of_month":
        return {o for o in options if o in numbers}
    if slot == "amount_rupees":
        return {o for o in options for n in numbers if n and any(n * u == o for u in _AMOUNT_UNITS)}
    return set()


def pick(slot: Slot, options: Sequence[Value], text: str, heard: Value | None = None) -> Value | None:
    """The option one transcript of the caller's answer chooses, or None unless it names exactly one.

    `options` must be in spoken order, because "the second one" refers to that order. An answer naming two
    options ("do nahi, saat") is left unresolved: which one was rejected is not safe to infer from words.
    """
    full = canon(slot, heard)
    if full is not None and full in options:
        return full
    chosen = {options[i] for i, rx in enumerate(_PICK_ORDINAL[: len(options)]) if rx.search(text)}
    chosen |= {options[i] for i, rx in enumerate(_PICK_ORDINAL_TE[: len(options)]) if rx.search(text)}
    chosen |= _short_matches(slot, options, small_numbers(text))
    return next(iter(chosen)) if len(chosen) == 1 else None
