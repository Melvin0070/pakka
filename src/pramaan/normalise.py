"""Inverse text normaliser: spoken amounts, dates, weekdays and phone numbers -> typed values.

Pure, deterministic, hand-written. Input is ASR text in Devanagari, Roman Hinglish or English,
often mixed within one utterance.

Matching. Each word is reduced to a spelling-insensitive key before lookup, so ASR variance
collapses onto one entry: Devanagari drops nukta/visarga, folds chandrabindu into anusvara,
long i/u into short, and a half nasal before a consonant into anusvara (पाँच=पांच, हज़ार=हजार,
छः=छ, पन्द्रह=पंद्रह, अड़तालिस=अड़तालीस); Roman lowercases, z->j, w->v, ee->i, oo->u, collapses
doubled letters and drops a word-final h after a vowel (hazaar=hajar, sattaees=sataees,
barah=bara). Text is normalised per token, so entity spans index the caller's original string.

English number words are also accepted in Devanagari spelling (नाइन, सैवन, थाउज़ेंड, फिफ्टींथ).
Unknown Devanagari words fall back to two cheap rules: थाउ…/हंड्र… prefixes are scales
(garbled endings like थाउजेंऑ), and an English cardinal stem + थ/एथ is an ordinal.

Choices worth knowing:
- "oh"/ओ is zero only inside a phone digit run.
- Ambiguous words are numbers only in a numeric context: साथ/saath (60 vs "with") needs a
  preceding number or a following scale ("chhe sau saath" = 660, "mere saath" = nothing);
  सो/so (100 vs "sleep"/"so") only right after a multiplier; "a" only before a scale;
  उन/un only before a tens word, where it means tens-1 (ASR splits उनचालीस as "उन चालीस").
- Amounts: a phrase is an amount if it is >= 100, uses a fraction idiom (sava/saadhe/paune/
  dedh/dhai), or has a currency cue (₹/Rs/rupaye before or after, or "ka/ke/ki <payment noun>").
  Small bare numbers without a cue are dropped, so "ek call" and "do din" yield nothing.
- A number directly followed by तारीख/tareekh/date is a day_of_month (1-31 only, never an
  amount); a trailing "<n> tareekh" is not absorbed into a preceding amount ("ek lakh bees
  hazaar unattees tareekh" = 120000 and 29). English ordinals ("fifteenth", "30th",
  "twenty first") are days; "first"/"second" need "the"/"on" before or a date word after.
- Phones: a run of digit words / digit strings (also double/triple X and pair readings like
  "ninety eight") with >= 8 digits is a phone, never an amount. +91/91 and a leading 0 are
  stripped. Value is the 10-digit string when valid (starts 6-9); otherwise the raw digit
  string of whatever length, on purpose, so the guard sees malformed numbers rather than
  silence. A run gives back its trailing word if that word starts an amount or date
  ("... teen zero, do sau rupaye").
- Not handled: years vs amounts (2025 is an amount), paise, numbers above 99 crore,
  Hindi ordinals (पहली, दूसरी), month names.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel

from .lexicon import (
    EN_DIGITS,
    EN_DIGITS_DEV,
    EN_WEEKDAYS_DEV,
    HI_0_99,
    HI_FRACTIONS,
    HI_SCALES,
    HI_WEEKDAYS,
    WEEKDAYS,
)
from .types import Slot, Value

__all__ = ["Entity", "extract", "parse_number", "values"]


class Entity(BaseModel, frozen=True):
    slot: Slot
    value: Value
    start: int
    end: int
    text: str


# ---------------------------------------------------------------- spelling keys

_DEV_RE = re.compile("[ऀ-ॿ]")
_DEV_FOLD = str.maketrans(
    {
        "़": None,  # nukta
        "ः": None,  # visarga
        "ऽ": None,  # avagraha
        "‌": None,
        "‍": None,
        "ँ": "ं",  # chandrabindu -> anusvara
        "ॉ": "ौ",  # candra o (ॉ) -> au
        "ी": "ि",  # ी -> ि
        "ू": "ु",  # ू -> ु
        "ई": "इ",
        "ऊ": "उ",
        "ै": "े",  # सैवन = सेवन, छै = छे
        "ऐ": "ए",
    }
)
_HALF_NASAL = re.compile("[ङञणनम]्(?=[क-ह])")


def _dev_key(w: str) -> str:
    w = unicodedata.normalize("NFD", w).translate(_DEV_FOLD)
    return unicodedata.normalize("NFC", _HALF_NASAL.sub("ं", w))


def _rom_key(w: str) -> str:
    w = unicodedata.normalize("NFKD", w.lower())
    w = "".join(c for c in w if "a" <= c <= "z")
    for a, b in (("ph", "f"), ("z", "j"), ("w", "v"), ("q", "k"), ("ee", "i"), ("oo", "u")):
        w = w.replace(a, b)
    w = re.sub(r"(.)\1+", r"\1", w)
    return re.sub(r"([aeiou])h$", r"\1", w)


def _key(w: str) -> str:
    return _dev_key(w) if _DEV_RE.search(w) else _rom_key(w)


# ---------------------------------------------------------------- lexicon

_Kind = Literal[
    "num", "scale", "frac", "rep", "ord", "cur", "date", "wd", "un", "and", "a", "money", "poss", "the"
]


@dataclass(frozen=True, slots=True)
class _Lex:
    kind: _Kind
    n: int = 0
    word: str = ""  # fraction name or weekday
    en: bool = False  # English number word: tens compose with a following unit
    weak: bool = False


_LEX: dict[str, _Lex] = {}


def _add(lex: _Lex, *words: str) -> None:
    for w in words:
        k = _key(w)
        old = _LEX.setdefault(k, lex)
        if old != lex:
            raise AssertionError(f"normalise lexicon collision on {w!r} ({k}): {old} vs {lex}")


# One line per value 0-99; first word is the common spelling, the rest are ASR/romanisation variants.
_HI_ROMAN = """
shunya shuny sunya shunye
ek
do
teen
chaar
paanch paach
chhah chhe che chheh
saat
aath
nau
das dus
gyaarah gyara igyarah egyarah gyaraah
baarah bara
terah
chaudah chodah choudah chaudha
pandrah pundrah pandhra pandara
solah
satrah sattrah satarah
athaarah attharah athrah
unnees unnis unees unnish
bees
ikkees ekkis
baaees baais bayees baayis
teyees teis teyis taees tais
chaubees chobis choubis chaubish
pachchees pachees pacchis pachhis
chhabbees chabees
sattaees sattais sattaais sattayis
atthaees atthais attaees attais
untees unattees unatis unthis
tees
ikattees iktees ikatis
battees
taintees tetis taitees tentis taitis
chauntees chontis chautis chontees
paintees pentis paitis paitees
chhattees
saintees sentis saitis saitees
adtees artis artees adhtis
untaalees untalis unatalis untalees
chaalees
iktaalees ikatalis
bayaalees byalis beyalis
taintaalees tentalis taitalis tetalis
chauvaalees chavalis chaualis chaualees
paintaalees pentalis paitalis
chhiyaalees chiyalis
saintaalees sentalis saitalis
adtaalees artalis adhtalis
unchaas
pachaas
ikyaavan ikkyavan ekyavan
baavan
tirpan tirepan trepan tirapan
chauvan chovan
pachpan pachapan
chhappan
sattaavan
atthaavan athavan
unsath unsaath unsadh unasath
saath
iksath ikasath
baasath
tirsath tiresath tirasath
chaunsath chausath chosath
painsath paisath pensath
chhiyaasath chhiasath
sadsath sarsath sadasath
adsath arsath adhsath adasath
unhattar unahattar
sattar
ikhattar ikahattar
bahattar behattar
tihattar
chauhattar chohattar
pachhattar pachattar pachahattar
chhihattar chhiyattar
satattar sathattar satahattar
athhattar athattar athahattar
unaasi unyasi unnasi
assi
ikyaasi
bayaasi byasi
tiraasi
chauraasi chorasi
pachaasi
chhiyaasi
sattaasi
atthaasi athasi
navaasi
nabbe nabbey nabe
ikyaanve ikyanave ikyanbe
baanve baanave
tiraanve tiranave
chauraanve chauranave choranve
pachaanve panchanve pachanave
chhiyaanve
sattaanve
atthaanve athanve
ninyaanve ninanve ninyanave
"""

_HI_DEV_ALT: dict[int, tuple[str, ...]] = {
    0: ("सुन्य", "शुन्य"),
    5: ("पांच",),
    6: ("छः", "छ", "छे", "छै"),
    11: ("इग्यारह", "ग्यारा"),
    12: ("बारा",),
    14: ("चौदा",),
    15: ("पन्द्रह", "पंद्रा", "पन्द्रा"),
    16: ("सोला",),
    17: ("सतरह", "सत्रा"),
    18: ("अठारा", "अट्ठारह"),
    19: ("उनीस",),
    21: ("एक्कीस",),
    22: ("बाइस",),
    23: ("तेइस",),
    25: ("पचीस",),
    26: ("छबीस",),
    27: ("सताईस",),
    28: ("अठ्ठाईस", "अठाईस"),
    29: ("उनत्तीस", "उन्तीस"),
    31: ("इकत्तीस",),
    32: ("बतीस",),
    33: ("तेंतीस", "तैतीस", "तेतीस"),
    34: ("चौतीस",),
    35: ("पैतीस", "पेंतीस"),
    36: ("छतीस",),
    37: ("सैतीस",),
    39: ("उन्तालीस",),
    41: ("इक्तालीस",),
    42: ("बियालीस", "ब्यालीस"),
    43: ("तैतालीस", "तेंतालीस"),
    44: ("चवालीस", "चौंवालीस"),
    45: ("पैतालीस", "पेंतालीस"),
    46: ("छयालीस",),
    47: ("सैतालीस",),
    49: ("उन्चास",),
    51: ("इक्कावन", "इक्यवन"),
    53: ("तिरेपन", "त्रेपन"),
    54: ("चव्वन",),
    57: ("सतावन",),
    58: ("अठावन", "अट्ठावन"),
    59: ("उन्सठ",),
    61: ("इक्सठ",),
    63: ("तिरेसठ",),
    64: ("चौसठ",),
    65: ("पैसठ",),
    66: ("छाछठ",),
    67: ("सरसठ",),
    72: ("बहतर",),
    75: ("पछत्तर",),
    76: ("छहत्तर",),
    77: ("सत्तत्तर",),
    78: ("अठत्तर",),
    79: ("उन्यासी", "उनयासी"),
    81: ("इकासी",),
    82: ("बियासी",),
    87: ("सतासी",),
    88: ("अठासी",),
    91: ("इक्यान्वे",),
    92: ("बान्वे",),
    93: ("तिरान्वे",),
    94: ("चौरान्वे", "चौरनवे"),
    95: ("पंचानवे", "पचानवे", "पचान्वे", "पंचान्वे"),
    96: ("छियान्वे",),
    97: ("सत्तान्वे",),
    98: ("अठानवे", "अट्ठान्वे"),
    99: ("निन्यानबे", "निन्यान्वे", "निनानवे"),
}

_EN_TEENS = ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
             "eighteen", "nineteen")  # fmt: skip
_EN_TENS = {20: ("twenty",), 30: ("thirty",), 40: ("forty", "fourty"), 50: ("fifty",), 60: ("sixty",),
            70: ("seventy",), 80: ("eighty",), 90: ("ninety",)}  # fmt: skip
# English number words as Hindi acoustic models spell them in Devanagari.
_EN_DEV: dict[int, tuple[str, ...]] = {
    0: ("जीरो", "ज़ेरो", "जिरो"), 1: ("वन्न",), 2: ("टु", "टू"), 3: ("थ्री", "थ्रि", "थ्रे"),
    4: ("फोर", "फौर", "फ़ोर"), 5: ("फाइव", "फ़ाइव", "फाईव", "फाइभ"), 6: ("सिक्स", "सिक्स़"),
    7: ("सेवेन", "सेवन", "सैवन", "सेवान"), 8: ("एइट", "ऐट", "एट"), 9: ("नाइन", "नाईन", "नायन"),
    10: ("टेन",), 11: ("इलेवन", "इलेवेन", "इलेवंन"), 12: ("ट्वेल्व", "ट्वेल्भ", "ट्वेल्फ"),
    13: ("थर्टीन", "थर्टिन", "थर्टींन"), 14: ("फोर्टीन", "फ़ोर्टीन", "फॉर्टीन"),
    15: ("फिफ्टीन", "फ़िफ़्टीन", "फिफ्टिन"), 16: ("सिक्सटीन", "सिक्स्टीन"),
    17: ("सेवनटीन", "सेवेनटीन", "सेवेंटीन", "सेवंटीन"), 18: ("एटीन", "एइटीन", "ऐटीन"),
    19: ("नाइनटीन", "नाइंटीन"), 20: ("ट्वेंटी", "ट्वेन्टी", "टवेंटी", "ट्वेंटि", "ट्वेनटी"),
    30: ("थर्टी", "थर्टि"), 40: ("फोर्टी", "फ़ॉर्टी", "फॉर्टी"), 50: ("फिफ्टी", "फ़िफ़्टी"),
    60: ("सिक्सटी", "सिक्स्टी"), 70: ("सेवेंटी", "सेवनटी", "सेवंटी", "सेवेनटी"),
    80: ("एटी", "एइटी", "ऐटी"), 90: ("नाइनटी", "नाइंटी", "नाइन्टी"),
}  # fmt: skip
_EN_DEV_ORD: dict[int, tuple[str, ...]] = {
    1: ("फर्स्ट", "फ़र्स्ट", "फस्ट"), 2: ("सेकंड", "सेकेंड", "सेकण्ड"), 3: ("थर्ड",), 5: ("फिफ्थ", "फ़िफ़्थ"),
    8: ("एट्थ", "एइथ", "एथ"), 9: ("नाइंथ", "नाइन्थ"), 12: ("ट्वेल्फ्थ", "ट्वेल्थ"),
}  # fmt: skip
_EN_ORD = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
           "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
           "eighteenth", "nineteenth", "twentieth")  # fmt: skip

_WEEKDAY_ALT: dict[str, tuple[str, ...]] = {
    "monday": ("somvaar", "somvar", "somwar", "मन्डे", "मनडे", "मंडै"),
    "tuesday": ("mangalvaar", "mangalwar", "mangal", "ट्यूजडे", "ट्यूसडे", "ट्यूस्डे", "ट्यूज्डे", "थुस्डे",
                "थुसडे", "टयूजडे", "ट्युजडे"),
    "wednesday": ("budhvaar", "budhwar", "budh", "वेनसडे", "वेनस्डे", "वेन्सडे", "वेडनस्डे", "वेडनसडे",
                  "वेडनेस्डे", "वैंसडे"),
    "thursday": ("guruvaar", "guruwar", "brihaspativaar", "brihaspatvar", "brahaspativar", "veervaar",
                 "virvar", "बिरस्पतवार", "थर्स्डे", "थर्ज़डे", "थर्सडै", "थरसडे"),
    "friday": ("shukravaar", "shukrawar", "sukravar", "shukra", "फ्राईडे", "फ्रायडे", "फराइडे"),
    "saturday": ("shanivaar", "shaniwar", "sanivar", "shani", "सैटर्डे", "सेटरडे", "सटरडे", "सैटरडै"),
    "sunday": ("ravivaar", "raviwar", "itvaar", "itwar", "etvaar", "aitvaar", "aitwar", "एतवार", "ऐतवार",
               "सन्डे", "सनडे"),
}  # fmt: skip

_FRAC_ALT: dict[str, tuple[str, ...]] = {
    "sava": ("sava", "savaa", "sawa", "swa", "savva", "सावा", "सव्वा"),
    "saadhe": ("saadhe", "saade", "saadhey", "saarhe", "sadhe", "sade", "साढे", "साड़े", "सढ़े"),
    "paune": ("paune", "pone", "paone", "poune", "paunay", "pauney", "पोने", "पउने"),
    "dedh": ("dedh", "derh", "dhedh", "डेढ", "डेड़", "ड्योढ़"),
    "dhai": ("dhai", "dhaai", "adhai", "adhaai", "dhaayi", "अढ़ाई", "अढाई", "ढाइ"),
}


def _build() -> None:
    for n, line in enumerate(_HI_ROMAN.strip().splitlines()):
        words = line.split()
        # साथ/saath also means "with"; see module docstring.
        _add(_Lex("num", n, weak=n == 60), *words)
    for n, w in enumerate(HI_0_99):
        _add(_Lex("num", n), w)
    _add(_Lex("num", 60, weak=True), "साथ")
    for n, alts in _HI_DEV_ALT.items():
        _add(_Lex("num", n), *alts)
    for n, w in enumerate(EN_DIGITS):
        _add(_Lex("num", n, en=True), w, EN_DIGITS_DEV[n])
    for n, w in enumerate(_EN_TEENS, 10):
        _add(_Lex("num", n, en=True), w)
    for n, ws in _EN_TENS.items():
        _add(_Lex("num", n, en=True), *ws)
    for n, ws in _EN_DEV.items():
        _add(_Lex("num", n, en=True), *ws)

    for unit, w in HI_SCALES.items():
        _add(_Lex("scale", unit), w)
    _add(_Lex("scale", 100), "sau", "sao", "hundred", "hundreds", "हंड्रेड", "हन्ड्रेड", "हंड्रड", "हंड्रेड्स")
    _add(_Lex("scale", 100, weak=True), "so", "सो")
    _add(_Lex("scale", 1000), "hazaar", "hazzar", "hajaar", "thousand", "thousands", "हजारों",
         "थाउजंड", "थाउज़ेंड", "थाउसेंड", "थाउजेंड", "थाउज़न्ड", "थाउजेन्ड")  # fmt: skip
    _add(_Lex("scale", 100_000), "lakh", "lakhs", "lac", "lacs", "laakh", "lak", "लाखों", "लख")
    _add(_Lex("scale", 10_000_000), "crore", "crores", "karod", "karor", "करोड", "क्रोड़")

    for name, alts in _FRAC_ALT.items():
        _add(_Lex("frac", word=name), HI_FRACTIONS[name], *alts)
    _add(_Lex("rep", 2), "double", "dubble", "डबल", "डब्बल", "डबुल")
    _add(_Lex("rep", 3), "triple", "tripple", "ट्रिपल", "ट्रिप्पल")
    for n, w in enumerate(_EN_ORD, 1):
        _add(_Lex("ord", n), w)
    _add(_Lex("ord", 30), "thirtieth")
    for n, ws in _EN_DEV_ORD.items():
        _add(_Lex("ord", n), *ws)
    # "oh" for zero only ever appears inside phone numbers.
    _add(_Lex("num", 0, en=True, weak=True), "oh", "ओ")

    for day in WEEKDAYS:
        _add(_Lex("wd", word=day), day, *HI_WEEKDAYS[day], *EN_WEEKDAYS_DEV[day], *_WEEKDAY_ALT[day])

    # Only symbols and abbreviations may precede the number; "rupaye do" means "give rupees".
    _add(_Lex("cur", word="pre"), "rs", "inr")
    _add(_Lex("cur"), "rupaye", "rupaiye", "rupaiya", "rupaya", "rupiya", "rupiye", "rupay", "rupai",
         "rupees", "rupee", "bucks", "रुपये", "रुपए", "रुपया", "रुपय", "रूपये", "रूपए",
         "रुपइया", "रुपैया", "रुपीस", "रुपीज़", "रूपीज", "रुपीज़्", "रुपिस", "रु", "रू")  # fmt: skip
    _add(_Lex("date"), "tareekh", "tarikh", "tareek", "tarik", "date", "तारीख", "तारिख", "तारीक", "तरीख",
         "डेट")  # fmt: skip
    _add(_Lex("money"), "payment", "recharge", "bill", "emi", "charge", "fee", "fees", "balance", "loan",
         "cheque", "check", "order", "cash", "advance", "amount", "rent", "kiraya", "deposit", "transfer",
         "installment", "kisht", "पेमेंट", "रिचार्ज", "रीचार्ज", "बिल", "ईएमआई", "चार्ज", "फीस", "बैलेंस",
         "लोन", "चेक", "ऑर्डर", "कैश", "एडवांस", "अमाउंट", "किराया", "किस्त", "ट्रांसफर", "डिपॉजिट")  # fmt: skip
    _add(_Lex("poss"), "ka", "ke", "ki", "का", "के", "की")
    _add(_Lex("un"), "un", "उन")
    _add(_Lex("and"), "and", "aur", "और", "एंड", "ऐंड", "एन्ड")
    _add(_Lex("a"), "a")
    _add(_Lex("the"), "the", "on", "द", "दि", "ऑन", "आन")


_build()

# ---------------------------------------------------------------- tokens

_TOKEN = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+(?!,?\d)|\d{1,3}(?:,\d{2})*,\d{3}(?!,?\d)|\d+(?:\.\d+)?)"
    r"(?P<suf>(?:k|K|st|nd|rd|th)(?![A-Za-z])|थ(?![ऀ-ॿ]))?"
    r"|(?P<word>[A-Za-z̀-ͯऀ-ॣॱ-ॿ‌‍']+)"
    r"|(?P<sym>₹)"
)
_GLUE = re.compile(r"[\s,\-–—/+]*")  # may sit inside one spoken number or digit run
_PREV_CUE_GAP = re.compile(r"[\s.:\-]*")
_ORD_SUFFIX = ("st", "nd", "rd", "th", "थ")  # "15थ": a recogniser writing "15th" in Devanagari


@dataclass(frozen=True, slots=True)
class _Tok:
    kind: _Kind | None
    start: int
    end: int
    num: Fraction = Fraction(0)
    word: str = ""
    en: bool = False
    weak: bool = False
    digits: str | None = None  # plain digit string, eligible for a phone run
    lit: bool = False  # written with digits rather than words


_DEV_PREFIX = tuple((_dev_key(p), _Lex("scale", n)) for p, n in (("थाउ", 1000), ("हंड्र", 100)))
_ORD_TAIL = re.compile("(?:ि?[एय]|इ)?्?थ्?$")


def _lookup(word: str) -> _Lex | None:
    k = _key(word)
    if (lex := _LEX.get(k)) is not None or not _DEV_RE.search(word):
        return lex
    # Garbled ASR endings: थाउजेंऑ, हंड्रे are still unambiguous from their first syllables.
    for prefix, lex in _DEV_PREFIX:
        if k.startswith(prefix):
            return lex
    # Devanagari English ordinals are the cardinal plus -th: फिफ्टींथ, सेवंथ, ट्वेंटिएथ.
    stem = _ORD_TAIL.sub("", k)
    if stem != k and stem:
        if stem.endswith("ं"):
            stem = stem[:-1] + "न"
        base = _LEX.get(stem) or _LEX.get(stem + "ि")
        if base is not None and base.kind == "num" and base.en and not base.weak and base.n in _ORD_OK:
            return _Lex("ord", base.n)
    return None


_ORD_OK = frozenset([*range(1, 21), 30])


def _ascii_digits(s: str) -> str:
    return "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in s)


def _tokenise(text: str) -> list[_Tok]:
    out: list[_Tok] = []
    for m in _TOKEN.finditer(text):
        s, e = m.span()
        if m.group("sym"):
            out.append(_Tok("cur", s, e, word="pre"))
        elif m.group("word"):
            lex = _lookup(m.group("word"))
            if lex is None:
                out.append(_Tok(None, s, e))
            else:
                out.append(_Tok(lex.kind, s, e, Fraction(lex.n), lex.word, lex.en, lex.weak))
        else:
            raw = _ascii_digits(m.group("num"))
            suf = (m.group("suf") or "").lower()
            val = Fraction(raw.replace(",", ""))
            if suf in _ORD_SUFFIX:
                out.append(_Tok("ord" if val.denominator == 1 else None, s, e, val, lit=True))
            elif suf == "k":
                out.append(_Tok("num", s, e, val * 1000, lit=True))
            else:
                plain = raw if raw.isdigit() else None
                out.append(_Tok("num", s, e, val, digits=plain, lit=True))
    return out


# ---------------------------------------------------------------- parser

_Span = tuple[Fraction, int]  # value, index one past the last consumed token


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.toks = _tokenise(text)
        self.link = [
            _GLUE.fullmatch(text, a.end, b.start) is not None
            for a, b in zip(self.toks, self.toks[1:], strict=False)
        ]

    def nx(self, i: int) -> int | None:
        """Index of the token after i if nothing but glue separates them."""
        return i + 1 if 0 <= i < len(self.link) and self.link[i] else None

    def kind(self, i: int | None) -> _Kind | None:
        return self.toks[i].kind if i is not None and 0 <= i < len(self.toks) else None

    def scale(self, i: int | None) -> _Tok | None:
        return self.toks[i] if i is not None and self.kind(i) == "scale" else None

    # A number below 100 (or a digit literal of any size) usable as a multiplier or a final term.
    def small(self, i: int, cont: bool) -> _Span | None:
        t = self.toks[i]
        j = self.nx(i)
        if t.kind == "num":
            if t.weak and not (cont or self.scale(j)):
                return None
            if t.en and not t.lit and t.num in _TENS and j is not None:
                u = self.toks[j]
                if u.kind == "num" and u.en and not u.lit and 1 <= u.num <= 9:
                    return t.num + u.num, j + 1
            return t.num, i + 1
        if t.kind == "un" and j is not None:
            u = self.toks[j]
            if u.kind == "num" and not u.en and not u.lit and u.num in _TENS:
                return u.num - 1, j + 1
        if t.kind == "a" and (sc := self.scale(j)) is not None and not sc.weak:
            return Fraction(1), i + 1
        return None

    def term(self, i: int, cont: bool) -> tuple[Fraction, int, int, bool] | None:
        """(value, unit, next index, used a fraction idiom)."""
        t = self.toks[i]
        if t.kind == "frac":
            j = self.nx(i)
            if j is None:
                return None
            if t.word in ("dedh", "dhai"):
                if (sc := self.scale(j)) is None:
                    return None
                unit = int(sc.num)
                return (Fraction(3, 2) if t.word == "dedh" else Fraction(5, 2)) * unit, unit, j + 1, True
            n, k = Fraction(1), j
            r = self.small(j, cont=True)
            if r is not None and r[0] < 100 and self.scale(self.nx(r[1] - 1)):
                n, k = r[0], r[1]
            elif t.word == "saadhe":
                return None
            if (sc := self.scale(k)) is None:
                return None
            unit = int(sc.num)
            q = {"sava": Fraction(1, 4), "saadhe": Fraction(1, 2), "paune": Fraction(-1, 4)}[t.word]
            return (n + q) * unit, unit, k + 1, True
        if t.kind == "scale" and not t.weak and not cont and self.kind(self.nx(i)) == "cur":
            return t.num, int(t.num), i + 1, False  # "सौ रुपये": a bare scale is one of it
        r = self.small(i, cont)
        if r is None:
            return None
        n, j = r
        s = self.nx(j - 1)
        if s is None or (sc := self.scale(s)) is None:
            return n, 1, j, False
        unit = int(sc.num)
        if unit == 100:
            # "one hundred twenty thousand", "do sau pachaas hazaar": a hundreds group under a bigger scale.
            g, k = n * 100, s + 1
            m = self.nx(s)
            if m is not None and self.kind(m) == "and":
                m = self.nx(m)
            if m is not None and (r2 := self.small(m, cont=True)) is not None and r2[0] < 100:
                g2, k2 = g + r2[0], r2[1]
            else:
                g2, k2 = g, k
            big = self.nx(k2 - 1)
            if big is not None and (bs := self.scale(big)) is not None and bs.num >= 1000:
                return g2 * int(bs.num), int(bs.num), big + 1, False
        return n * unit, unit, s + 1, False

    def amount(self, i: int) -> tuple[Fraction, int, bool] | None:
        total, prev, end, frac = Fraction(0), Fraction(10**12), None, False
        j: int | None = i
        while j is not None:
            r = self.term(j, cont=end is not None)
            if r is None:
                break
            v, unit, k, fr = r
            if unit >= prev or v >= prev:
                break
            if unit == 1 and end is not None and self.kind(self.nx(k - 1)) == "date":
                break
            total, prev, end, frac = total + v, Fraction(unit), k, frac or fr
            j = self.nx(k - 1)
            if j is not None and self.kind(j) == "and":
                j = self.nx(j)
        if end is None or total.denominator != 1:
            return None
        return total, end, frac

    def phone(self, i: int) -> tuple[str, int] | None:
        if i > 0 and self.kind(i - 1) == "cur" and self.toks[i].lit:
            return None
        parts: list[tuple[str, int]] = []  # (digits, end index)
        j: int | None = i
        while j is not None:
            t = self.toks[j]
            k = self.nx(j)
            if t.kind == "rep" and k is not None:
                d = self.toks[k]
                if (
                    d.kind == "num"
                    and (d.en or not d.weak)
                    and d.num < 10
                    and (not d.lit or d.digits is not None)
                ):
                    parts.append((str(int(d.num)) * int(t.num), k + 1))
                    j = self.nx(k)
                    continue
                break
            if t.kind != "num" or (t.weak and not t.en):
                break
            if t.digits is not None:
                parts.append((t.digits, j + 1))
            elif t.weak:
                parts.append(("0", j + 1))
            elif t.lit or t.num.denominator != 1 or t.num >= 100:
                break
            else:
                r = self.small(j, cont=False)
                assert r is not None
                parts.append((str(int(r[0])), r[1]))
                k = self.nx(r[1] - 1)
            j = k
        while parts and self.kind(self.nx(parts[-1][1] - 1)) in ("scale", "date", "cur", "frac"):
            parts.pop()
        digits = "".join(p for p, _ in parts)
        if len(digits) < 8:
            return None
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        return digits, parts[-1][1]

    def ordinal(self, i: int) -> tuple[int, int] | None:
        t = self.toks[i]
        if t.kind == "ord":
            v, end = int(t.num), i + 1
        elif t.kind == "num" and t.en and not t.lit and t.num in (20, 30):
            j = self.nx(i)
            if j is None:
                return None
            u = self.toks[j]
            if u.kind != "ord" or u.lit or u.num > 9:
                return None
            v, end = int(t.num + u.num), j + 1
        else:
            return None
        if not 1 <= v <= 31:
            return None
        if v <= 2 and not t.lit:
            # "first"/"second" are everyday words; demand a date-ish neighbour.
            before = self.kind(i - 1) == "the" if i > 0 else False
            if not (before or self.kind(self.nx(end - 1)) == "date"):
                return None
        return v, end

    def after_on_the(self, i: int) -> bool:
        return i >= 2 and self.kind(i - 1) == "the" and self.kind(i - 2) == "the" and self.nx(i - 2) == i - 1

    def has_money_cue(self, i: int, end: int) -> bool:
        prev = self.toks[i - 1] if i > 0 else None
        if prev is not None and prev.kind == "cur" and prev.word == "pre":
            if _PREV_CUE_GAP.fullmatch(self.text, prev.end, self.toks[i].start):
                return True
        j = self.nx(end - 1)
        if j is None:
            return False
        return self.kind(j) in ("cur", "money") or (
            self.kind(j) == "poss" and self.kind(self.nx(j)) == "money"
        )

    def entity(self, slot: Slot, value: Value, i: int, end: int) -> Entity:
        s, e = self.toks[i].start, self.toks[end - 1].end
        return Entity(slot=slot, value=value, start=s, end=e, text=self.text[s:e])

    def extract(self) -> list[Entity]:
        out: list[Entity] = []
        i, n = 0, len(self.toks)
        while i < n:
            t = self.toks[i]
            if t.kind == "wd":
                out.append(self.entity("weekday", t.word, i, i + 1))
                i += 1
                continue
            if (o := self.ordinal(i)) is not None:
                out.append(self.entity("day_of_month", o[0], i, o[1]))
                i = o[1]
                continue
            if (p := self.phone(i)) is not None:
                out.append(self.entity("phone", p[0], i, p[1]))
                i = p[1]
                continue
            if (a := self.amount(i)) is not None:
                v, end, frac = a
                value = int(v)
                if self.kind(self.nx(end - 1)) == "date":
                    if 1 <= value <= 31:
                        out.append(self.entity("day_of_month", value, i, end))
                elif value >= 100 or frac or self.has_money_cue(i, end):
                    out.append(self.entity("amount_rupees", value, i, end))
                elif 1 <= value <= 31 and self.after_on_the(i):
                    # "on the 28" / "ऑन द सेवेनटीन": an English date with the ordinal ending lost.
                    out.append(self.entity("day_of_month", value, i, end))
                i = end
                continue
            i += 1
        return out


_TENS = frozenset(Fraction(t) for t in range(20, 100, 10))
_NUMERIC: frozenset[_Kind | None] = frozenset({"num", "scale", "frac", "un", "rep", "ord"})


def extract(text: str) -> list[Entity]:
    """All entities in text order. Spans index `text` as given and cover only the value words."""
    return _Parser(text).extract()


def values(text: str) -> dict[str, Value]:
    """slot -> value, taking the first entity of each slot."""
    out: dict[str, Value] = {}
    for e in extract(text):
        out.setdefault(e.slot, e.value)
    return out


def parse_number(text: str) -> int | None:
    """Value of a bare number phrase ("paune teen hazaar", "2,25,000", "fifteen hundred rupees").

    None unless the whole phrase is one number; currency words around it are ignored."""
    p = _Parser(text)
    starts = [i for i, t in enumerate(p.toks) if t.kind in _NUMERIC or t.kind == "a"]
    if not starts:
        return None
    r = p.amount(starts[0])
    if r is None:
        return None
    v, end, _ = r
    if any(t.kind in _NUMERIC for t in p.toks[end:]):
        return None
    return int(v)
