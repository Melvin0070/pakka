"""Typed value -> the ways a caller would say it, in Devanagari. First rendering is the plain form.

Used by the acoustic witness (what to score), the question phraser and the synthetic-data generator.
"""

from __future__ import annotations

from .lexicon import EN_DIGITS_DEV, EN_WEEKDAYS_DEV, HI_0_99, HI_FRACTIONS, HI_SCALES, HI_WEEKDAYS
from .types import Value

_UNITS = (10_000_000, 100_000, 1000, 100)


def hindi_cardinal(n: int) -> str:
    if not 0 <= n < 1_000_000_000:
        raise ValueError(n)
    if n < 100:
        return HI_0_99[n]
    parts: list[str] = []
    for unit in _UNITS:
        k, n = divmod(n, unit)
        if k:
            parts.append(f"{hindi_cardinal(k)} {HI_SCALES[unit]}")
    if n:
        parts.append(HI_0_99[n])
    return " ".join(parts)


def _fraction_forms(n: int) -> list[str]:
    out: list[str] = []
    for unit in _UNITS:
        if n * 4 % unit or n < unit:
            continue
        k, quarters = divmod(n * 4 // unit, 4)
        if quarters == 0 or k > (20 if unit == 100 else 99):
            continue
        scale = HI_SCALES[unit]
        if quarters == 1:
            out.append(f"{HI_FRACTIONS['sava']} {HI_0_99[k]} {scale}")
        elif quarters == 2:
            head = {1: HI_FRACTIONS["dedh"], 2: HI_FRACTIONS["dhai"]}.get(
                k, f"{HI_FRACTIONS['saadhe']} {HI_0_99[k]}"
            )
            out.append(f"{head} {scale}")
        elif k < 99:
            out.append(f"{HI_FRACTIONS['paune']} {HI_0_99[k + 1]} {scale}")
    return out


def amount_renderings(n: int) -> list[str]:
    forms = [hindi_cardinal(n)]
    forms += _fraction_forms(n)
    if n % 100 == 0 and n % 1000 and 1100 <= n <= 9900:
        forms.append(f"{HI_0_99[n // 100]} {HI_SCALES[100]}")  # "पचपन सौ"
    return list(dict.fromkeys(forms))


_EN_ONES = (
    "ज़ीरो वन टू थ्री फ़ोर फ़ाइव सिक्स सेवन एट नाइन टेन इलेवन ट्वेल्व थर्टीन फोर्टीन फिफ्टीन सिक्सटीन सेवेंटीन एटीन नाइनटीन"
).split()
_EN_TENS = "_ _ ट्वेंटी थर्टी फोर्टी फिफ्टी सिक्सटी सेवेंटी एटी नाइंटी".split()
_EN_ORDINALS = (
    "_ फर्स्ट सेकंड थर्ड फोर्थ फिफ्थ सिक्स्थ सेवंथ एट्थ नाइंथ टेंथ इलेवंथ ट्वेल्फ्थ थर्टींथ फोर्टींथ फिफ्टींथ "
    "सिक्सटींथ सेवेंटींथ एटींथ नाइनटींथ ट्वेंटिएथ"
).split()


def _en_below_100(k: int) -> str:
    return _EN_ONES[k] if k < 20 else _EN_TENS[k // 10] + (f" {_EN_ONES[k % 10]}" if k % 10 else "")


def _en_below_1000(k: int) -> str:
    h, r = divmod(k, 100)
    return " ".join(x for x in (f"{_EN_ONES[h]} हंड्रेड" if h else "", _en_below_100(r) if r else "") if x)


def english_amount_renderings(n: int) -> list[str]:
    """English number words in the Devanagari spelling a Hindi acoustic model emits."""
    if not 0 < n < 10_000_000:
        return []
    lakh, rest = divmod(n, 100_000)
    th, r = divmod(rest, 1000)
    parts = [
        f"{_en_below_100(lakh)} लाख" if lakh else "",
        f"{_en_below_1000(th)} थाउज़ेंड" if th else "",
        _en_below_1000(r) if r else "",
    ]
    forms = [" ".join(x for x in parts if x)]
    if n % 100 == 0 and n % 1000 and n < 10000:
        forms.append(f"{_en_below_100(n // 100)} हंड्रेड")
    return forms


def english_day_renderings(d: int) -> list[str]:
    if d <= 20:
        return [_EN_ORDINALS[d]]
    if d == 30:
        return ["थर्टिएथ"]
    return [f"{_EN_TENS[d // 10]} {_EN_ORDINALS[d % 10]}"]


def phone_renderings(digits: str) -> list[str]:
    hindi = " ".join(HI_0_99[int(d)] for d in digits)
    english = " ".join(EN_DIGITS_DEV[int(d)] for d in digits)
    return [hindi, english]


def renderings(slot: str, value: Value) -> list[str]:
    if slot == "amount_rupees":
        return amount_renderings(int(value)) + english_amount_renderings(int(value))
    if slot == "day_of_month":
        return [HI_0_99[int(value)], *english_day_renderings(int(value))]
    if slot == "weekday":
        return [*HI_WEEKDAYS[str(value)], *EN_WEEKDAYS_DEV[str(value)]]
    if slot == "phone":
        return phone_renderings(str(value))
    raise ValueError(slot)
