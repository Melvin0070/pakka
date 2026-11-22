"""Values a caller could plausibly have said instead: the alternatives the acoustic model must rule out.

Without these the witness has nothing to compare against whenever every transcriber returns the same value,
which is exactly when a shared mishearing would slip through.
"""

from __future__ import annotations

from .lexicon import WEEKDAYS
from .types import Value

# Digits that sound alike over a narrowband line, in Hindi or English.
_DIGIT_SWAPS = {"0": "2", "1": "9", "2": "3", "3": "2", "4": "1", "5": "9", "6": "7", "7": "8", "8": "7", "9": "5"}  # fmt: skip
MAX_AMOUNT = 12
MAX_PHONE = 24


# Telugu pairs that differ by one syllable: ఇరవై / అరవై, పదిహేను / పదిహేడు, ఎనిమిది / ఎనభై, తొమ్మిది / తొంభై.
_TE_SWAPS = {20: [60], 60: [20, 16], 15: [17], 17: [15], 8: [80], 80: [8, 70], 70: [80], 9: [90], 90: [9],
             3: [30], 30: [3], 4: [40], 40: [4], 6: [7], 7: [6], 16: [60], 12: [20]}  # fmt: skip


def _group_swaps(g: int, lang: str = "hi") -> list[int]:
    out: list[int] = []
    if lang == "te":
        if 13 <= g <= 19:  # callers mix in English: thirteen / thirty
            out.append((g - 10) * 10)
        if g % 10 == 0 and 30 <= g <= 90:
            out.append(g // 10 + 10)
        out += _TE_SWAPS.get(g, [])
        return [x for x in dict.fromkeys(out) if 0 < x < 100]
    if g % 10 == 9 and g >= 19:  # उनतीस / उनतालीस / उनचास differ in one medial syllable
        out += [g - 10, g + 10]
    if 13 <= g <= 19:  # thirteen / thirty
        out.append((g - 10) * 10)
    if g % 10 == 0 and 30 <= g <= 90:
        out.append(g // 10 + 10)
    out += {7: [8, 60], 8: [7], 60: [7, 70], 70: [60, 17], 17: [70], 2: [3], 3: [2], 25: [35, 45], 67: [77], 77: [67], 96: [99], 99: [96]}.get(g, [])  # fmt: skip
    return [x for x in out if 0 < x < 100]


def amount(n: int, lang: str = "hi") -> list[int]:
    out: list[int] = []
    for unit in (100_000, 1000, 100, 1):
        g = n // unit % 100
        out += [n + (x - g) * unit for x in _group_swaps(g, lang)]
    for unit in (100_000, 1000, 100):  # सवा / साढ़े / पौने and the whole number either side
        if n >= unit and n * 4 % unit == 0:
            out += [n + d * unit // 4 for d in (-2, -1, 1, 2)]
    for unit, other in (
        (1000, 100),
        (100, 1000),
        (100_000, 1000),
        (1000, 100_000),
    ):  # हज़ार heard as सौ, and so on
        if n % unit == 0 and n // unit < 100:
            out.append(n // unit * other)
    digits = str(n)
    if len(digits) > 2:  # a dropped syllable: 9999 -> 999, 3330 -> 3030
        out += [int(digits[:i] + digits[i + 1 :]) for i in range(len(digits))]
        out += [int(digits[:i] + "0" + digits[i + 1 :]) for i in range(1, len(digits)) if digits[i] != "0"]
    return [x for x in dict.fromkeys(out) if x > 0 and x != n][:MAX_AMOUNT]


def day(d: int) -> list[int]:
    return [x for x in range(1, 32) if x != d]


def weekday(w: str) -> list[str]:
    return [x for x in WEEKDAYS if x != w]


def phone(p: str) -> list[str]:
    if not p.isdigit():
        return []
    out = [p[:i] + _DIGIT_SWAPS[p[i]] + p[i + 1 :] for i in range(len(p))]
    for i in range(len(p) - 1):  # "double four" heard once or twice
        if p[i] == p[i + 1]:
            out += [p[:i] + p[i + 1 :], p[: i + 1] + p[i] + p[i + 1 :]]
    return [x for x in dict.fromkeys(out) if x != p][:MAX_PHONE]


def neighbours(slot: str, value: Value, lang: str = "hi") -> list[Value]:
    if slot == "amount_rupees" and isinstance(value, int):
        return list(amount(value, lang))
    if slot == "day_of_month" and isinstance(value, int):
        return list(day(value))
    if slot == "weekday" and isinstance(value, str):
        return list(weekday(value))
    if slot in ("phone", "pincode", "account_number") and isinstance(value, str):
        return list(phone(value))
    return []
