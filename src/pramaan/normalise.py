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

Telugu (Telugu script, a little Roman) shares the parser and differs in four ways, all in the lexer:
- A scale alone is one of it (వంద = 100, లక్ష యాభై వేలు = 1,50,000), and scales inflect (వందలు, వందల,
  వేలకు), so they match by stem.
- Above twenty a number is two words, ten then unit (ఇరవై ఐదు), composed like English "twenty five".
- Fractions are suffixes on the multiplier, not words before it: రెండున్నర వేలు = 2,500,
  లక్షన్నర = 1,50,000, రెండుంపావు లక్షలు = 2,25,000. Hundreds fuse too: రెండొందలు = 200.
- Recognisers often write a number without spaces (రెండువేల, ఇరవైఐదు). An unknown Telugu word is
  split where both halves are number words. Day ordinals are a suffix (ఇరవై ఐదో తేదీ, పదిహేనవ తేదీ).
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
    EN_DIGITS_TE,
    EN_WEEKDAYS_DEV,
    EN_WEEKDAYS_TE,
    HI_0_99,
    HI_FRACTIONS,
    HI_SCALES,
    HI_WEEKDAYS,
    TE_0_99,
    TE_FRACTIONS,
    TE_HALF_SUFFIX,
    TE_HUNDRED_AND,
    TE_SCALE_OBLIQUE,
    TE_SCALE_ONE,
    TE_SCALE_PLURAL,
    TE_TENS,
    TE_WEEKDAYS,
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


_TEL_RE = re.compile("[ఀ-౿]")
_TEL_FOLD = str.maketrans(
    {
        "‌": None,
        "‍": None,
        "ః": None,
        "ఁ": "ం",
        "ీ": "ి", "ూ": "ు", "ే": "ె", "ో": "ొ", "ఈ": "ఇ", "ఊ": "ఉ", "ఏ": "ఎ", "ఓ": "ఒ",
        # Aspiration and retroflex l/n are written inconsistently: యాభై / యాబై, ముప్పై / ముప్ఫై.
        "ఖ": "క", "ఘ": "గ", "ఛ": "చ", "ఝ": "జ", "ఠ": "ట", "ఢ": "డ", "థ": "త", "ధ": "ద", "ఫ": "ప",
        "భ": "బ", "ళ": "ల", "ణ": "న", "ఱ": "ర",
    }
)  # fmt: skip
_TEL_HALF_NASAL = re.compile("[ఙఞనమ]్(?=[క-హ])")
_TEL_GEMINATE = re.compile("([క-హ])్\\1")


def _tel_key(w: str) -> str:
    w = unicodedata.normalize("NFC", w).translate(_TEL_FOLD)
    return _TEL_HALF_NASAL.sub("ం", _TEL_GEMINATE.sub(r"\1", w))


def _key(w: str) -> str:
    if _DEV_RE.search(w):
        return _dev_key(w)
    return _tel_key(w) if _TEL_RE.search(w) else _rom_key(w)


# ---------------------------------------------------------------- lexicon

_Kind = Literal[
    "num", "scale", "frac", "rep", "ord", "cur", "date", "wd", "un", "and", "a", "money", "poss", "the"
]


@dataclass(frozen=True, slots=True)
class _Lex:
    kind: _Kind
    n: int | Fraction = 0
    word: str = ""  # fraction name or weekday
    en: bool = False  # English number word: tens compose with a following unit
    weak: bool = False
    te: bool = False  # Telugu number word: tens compose with a following unit, as in English
    bare: bool = False  # a scale that means one of itself when nothing multiplies it (Telugu వంద)
    unit: int = 1  # a word that already contains its scale (రెండొందలు, లక్షన్నర)


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

# One line per value; the first word is the lexicon spelling, the rest are variants recognisers write.
_TE_ALT: dict[int, tuple[str, ...]] = {
    0: ("సున్న", "సున్నా", "సొన్న"), 1: ("ఒకటి", "ఒక్కటి", "వకటి"), 2: ("రెండు",), 3: ("మూడు",),
    4: ("నాలుగు", "నాల్గు"), 5: ("ఐదు", "అయిదు", "అయ్దు"), 6: ("ఆరు",), 7: ("ఏడు",),
    8: ("ఎనిమిది", "ఎన్మిది", "ఎనమిది"), 9: ("తొమ్మిది",), 10: ("పది",),
    11: ("పదకొండు", "పదకొండ", "పదకండు"), 12: ("పన్నెండు", "పన్నెండ", "పండ్రెండు"), 13: ("పదమూడు",),
    14: ("పద్నాలుగు", "పదునాలుగు", "పధ్నాలుగు", "పద్నాల్గు"), 15: ("పదిహేను", "పదైదు", "పదిహేన"),
    16: ("పదహారు", "పదారు"), 17: ("పదిహేడు", "పదేడు"), 18: ("పద్దెనిమిది", "పదెనిమిది", "పద్ధెనిమిది", "పద్నెనిమిది"),
    19: ("పంతొమ్మిది", "పందొమ్మిది", "పంతొంది"),
    20: ("ఇరవై", "ఇరవయి", "ఇరవయ్", "ఇరువై"), 30: ("ముప్పై", "ముప్పయి", "ముప్పయ్", "ముప్ఫై", "ముఫ్ఫై"),
    40: ("నలభై", "నలభయి", "నలబై", "నలభయ్", "నాలభై"), 50: ("యాభై", "ఏభై", "యాబై", "యాభయి", "యాభయ్", "యాపై"),
    60: ("అరవై", "అరవయి", "అరవయ్"), 70: ("డెబ్బై", "డెబ్భై", "డెభ్భై", "డెబ్బయి", "డెబ్బయ్"),
    80: ("ఎనభై", "ఎనబై", "ఎనభయి", "ఎనభయ్"), 90: ("తొంభై", "తొంబై", "తొంభయి", "తొంభయ్", "తొంబయి"),
}  # fmt: skip
_TE_ROMAN: dict[int, tuple[str, ...]] = {
    0: ("sunna",), 1: ("okati", "okkati"), 2: ("rendu",), 3: ("moodu",), 4: ("naalugu", "nalgu"),
    5: ("aidu", "ayidu"), 6: ("aaru",), 7: ("edu",), 8: ("enimidi",), 9: ("tommidi", "thommidi"),
    10: ("padi",), 11: ("padakondu",), 12: ("pannendu",), 13: ("padamoodu",), 14: ("padnaalugu",),
    15: ("padihenu",), 16: ("padahaaru",), 17: ("padihedu",), 18: ("paddenimidi",),
    19: ("pantommidi", "panthommidi"), 20: ("iravai", "iravay"), 30: ("muppai", "muppay"),
    40: ("nalabhai", "nalabai"), 50: ("yaabhai", "yabai", "ebhai"), 60: ("aravai",),
    70: ("debbai", "debbhai"), 80: ("enabhai", "enabai"), 90: ("tombhai", "thombhai", "tombai"),
}  # fmt: skip
# English number words as Telugu recognisers spell them.
_EN_TE: dict[int, tuple[str, ...]] = {
    0: ("జీరో", "జిరో", "జీడో"), 1: ("వన్", "వన్ను", "వను"), 2: ("టూ", "టు", "ట్యూ", "ట్రూ", "త్రూ", "తూ"), 3: ("త్రీ", "థ్రీ", "త్రి"),
    4: ("ఫోర్", "ఫోరు", "ఫోర"), 5: ("ఫైవ్", "ఫైవు", "ఫైవ"), 6: ("సిక్స్", "సిక్సు", "సిక్స"),
    7: ("సెవెన్", "సెవన్", "సెవను", "సెవెను", "సెవెన"), 8: ("ఎయిట్", "ఎయిటు", "ఏట్", "ఎయ్ట్", "ఎయిత్", "ఐట్"),
    9: ("నైన్", "నైను", "నయిన్"), 10: ("టెన్", "టెను"), 11: ("ఎలెవెన్", "ఎలెవన్", "ఇలెవెన్", "లెవెన్"),
    12: ("ట్వెల్వ్", "ట్వెల్వు", "ట్వల్వ్", "ట్వెల్"), 13: ("థర్టీన్", "తర్టీన్"),
    14: ("ఫోర్టీన్", "ఫార్టీన్"), 15: ("ఫిఫ్టీన్", "ఫిఫ్టిను"), 16: ("సిక్స్టీన్", "సిక్స్‌టీన్"),
    17: ("సెవెంటీన్", "సెవెన్టీన్", "సెవన్టీన్", "సెవంటీన్"), 18: ("ఎయిటీన్", "ఎయిట్టీన్", "ఏటీన్"),
    19: ("నైన్టీన్", "నైంటీన్", "నైన్‌టీన్"), 20: ("ట్వంటీ", "ట్వెంటీ", "ట్వెన్టీ", "ట్వన్టీ", "టోంటీ"),
    30: ("థర్టీ", "తర్టీ"), 40: ("ఫార్టీ", "ఫోర్టీ"), 50: ("ఫిఫ్టీ",), 60: ("సిక్స్టీ", "సిక్స్‌టీ"),
    70: ("సెవెంటీ", "సెవెన్టీ", "సెవంటీ", "సెవన్టీ"), 80: ("ఎయిటీ", "ఏటీ"),
    90: ("నైంటీ", "నైన్టీ", "నైన్‌టీ"),
}  # fmt: skip
_TE_WEEKDAY_ALT: dict[str, tuple[str, ...]] = {
    "monday": ("somavaram", "somavaaram", "మన్డే", "మండె"),
    "tuesday": ("mangalavaram", "mangalavaaram", "ట్యూస్‌డే", "ట్యూజ్డే", "ట్యూజ్‌డే", "టూస్డే", "ట్యూస్ డే"),
    "wednesday": ("budhavaram", "budhavaaram", "వెడ్నెస్‌డే", "వెన్స్డే", "వెన్స్‌డే", "వెడ్నస్డే", "బుద్ధవారం"),
    "thursday": ("guruvaram", "guruvaaram", "థర్స్‌డే", "తర్స్డే", "థర్స్ డే", "గురవారం", "లక్ష్మీవారం"),
    "friday": ("shukravaram", "sukravaram", "shukravaaram", "ఫ్రైడే", "ఫ్రై డే", "శుక్కురవారం"),
    "saturday": ("shanivaram", "sanivaram", "shanivaaram", "సాటర్‌డే", "శాటర్డే", "సాటర్ డే", "సెటర్డే", "శనివారము"),
    "sunday": ("aadivaram", "adivaram", "aadivaaram", "సన్డే", "సండె"),
}  # fmt: skip
# Stems that keep their meaning under any case ending: రూపాయలకు, తేదీన, సోమవారానికి, వేలకు.
_TE_STEMS: list[tuple[str, _Lex]] = []


def _build_te() -> None:
    for n, words in _TE_ALT.items():
        _add(_Lex("num", n, te=True), TE_0_99[n] if n < 20 else TE_TENS[n], *words, *_TE_ROMAN[n])
    for n, words in _EN_TE.items():
        _add(_Lex("num", n, en=True), *words)
    for n, w in enumerate(EN_DIGITS_TE):
        _add(_Lex("num", n, en=True), w)
    # "One" before a scale drops its ending: ఒక లక్ష.
    _add(_Lex("num", 1, te=True, weak=True), "ఒక", "oka")
    for n, stem in ((20, "ఇరవయ్య"), (30, "ముప్పయ్య")):  # the day ordinals of the round tens
        _add(_Lex("num", n, te=True), stem + "ో", stem + "వ")

    for unit, w in TE_SCALE_ONE.items():
        _add(_Lex("scale", unit, bare=True), w)
    _add(_Lex("scale", 100, bare=True), TE_HUNDRED_AND, "నూరు", "వందా", "vanda", "nooru", "noota")
    _add(_Lex("scale", 1000, bare=True), "వేయి", "వెయి", "వయ్యి", "veyyi", "veyi")
    _add(_Lex("scale", 100_000, bare=True), "లక్షా", "laksha")
    _add(_Lex("scale", 10_000_000, bare=True), "koti")
    # Plural and oblique shapes need a multiplier: వేల రూపాయలు alone is "thousands of rupees", and a
    # garbled multiplier before it (ఏనీమడిన్నర వేల) must not collapse to one thousand.
    for table in (TE_SCALE_PLURAL, TE_SCALE_OBLIQUE):
        for unit, w in table.items():
            _add(_Lex("scale", unit, te=True), w)
    _add(_Lex("scale", 100, te=True), "vandalu", "vandala")
    _add(_Lex("scale", 1000, te=True), "velu", "vela")
    _add(_Lex("scale", 100_000, te=True), "lakshalu", "lakshala")
    _add(_Lex("scale", 10_000_000, te=True), "kotlu", "kotla")
    _add(_Lex("scale", 100), "హండ్రెడ్", "హండ్రడ్", "హండ్రెడ్స్", "హన్డ్రెడ్")
    _add(_Lex("scale", 1000), "థౌజండ్", "థౌసండ్", "తౌజండ్", "థౌజెండ్", "థౌజండ్స్", "థౌజన్డ్",
         "థౌసెండ్")  # fmt: skip
    _add(_Lex("scale", 100_000), "లాక్", "లాక్స్", "ల్యాక్", "లాఖ్")
    _add(_Lex("scale", 10_000_000), "క్రోర్", "క్రోర్స్", "కరోడ్")

    # A quarter, half or three quarters of the scale that follows; never a number on its own.
    for name, q in (
        ("quarter", Fraction(1, 4)),
        ("half", Fraction(1, 2)),
        ("three_quarters", Fraction(3, 4)),
    ):
        _add(_Lex("num", q, te=True, weak=True), TE_FRACTIONS[name])
    _add(_Lex("num", Fraction(1, 2), te=True, weak=True), "నర", "న్నర")  # the half suffix written apart
    _add(_Lex("rep", 2), "డబుల్", "డబ్బుల్", "డబల్", "డబో", "డబ్ల్")
    _add(_Lex("rep", 3), "ట్రిపుల్", "ట్రిపల్", "త్రిపుల్")

    for day in WEEKDAYS:
        _add(_Lex("wd", word=day), *TE_WEEKDAYS[day], *EN_WEEKDAYS_TE[day], *_TE_WEEKDAY_ALT[day])
        for w in TE_WEEKDAYS[day]:
            _TE_STEMS.append((_tel_key(w[:-1]), _Lex("wd", word=day)))  # drop the final ం
    _add(_Lex("cur"), "రూ", "rupayalu", "rupayi", "rupayala", "roopayalu", "రూపీస్", "రుపీస్", "రూపీ")
    _add(_Lex("date"), "తేదీ", "తారీఖు", "తారీకు", "tedi", "tedhi", "tareeku", "డేట్", "డేటు")
    _add(_Lex("money"), "పేమెంట్", "రీఛార్జ్", "రీచార్జ్", "బిల్లు", "బిల్", "ఈఎంఐ", "ఛార్జ్", "ఫీజు", "బ్యాలెన్స్",
         "లోన్", "చెక్", "చెక్కు", "ఆర్డర్", "క్యాష్", "అడ్వాన్స్", "అమౌంట్", "అద్దె", "కిస్తీ", "డిపాజిట్",
         "ట్రాన్స్ఫర్", "ట్రాన్స్‌ఫర్", "బాకీ", "addhe", "kisti")  # fmt: skip
    _add(_Lex("and"), "అండ్")
    _TE_STEMS.extend(
        (_tel_key(stem), lex)
        for stem, lex in (
            ("రూపాయ", _Lex("cur")), ("రుపాయ", _Lex("cur")), ("రూపాయి", _Lex("cur")), ("రూపాయిల", _Lex("cur")),
            ("తేదీ", _Lex("date")), ("తారీఖ", _Lex("date")), ("తారీక", _Lex("date")),
        )
    )  # fmt: skip


_build_te()
# Case endings a scale may carry: వేలకు, లక్షల్లో, వందలే.
_TE_CASE = re.compile("(?:ు|ా)?(?:కు|కి|లొ|ల్లొ|ని|ను|న|తొ|ె|కె|వరకు|దాకా)?")
# Postpositions a recogniser fuses onto the last word of a number: జీరోకి, ఎయిట్కి, యాభైకి.
_TE_FUSED = tuple(_tel_key(x) for x in ("కి", "కు", "ని", "ను", "లో", "నే", "కే", "తో"))
_TE_SCALE_STEMS = tuple((_tel_key(w), _Lex("scale", unit, te=True)) for unit, w in TE_SCALE_OBLIQUE.items())
_TE_HALF = _tel_key(TE_HALF_SUFFIX)
_TE_QUARTER = tuple(_tel_key(x) for x in ("ంపావు", "ంబావు", "పావు"))
_TE_HUNDREDS = tuple(_tel_key(x) for x in ("ొందలు", "ొందల", "ొంద", "వందలు", "వందల"))
_TE_ORDINAL = tuple(_tel_key(x) for x in ("ో", "వ", "వది", "వ తేదీ"))[:3]
_TE_VOWEL_ENDS = ("", "ు", "ి")
# ఇరవై -> ఇరవయ: the stem a ten takes when the unit's first vowel fuses onto it.
_TE_TENS_STEMS = tuple((n, _tel_key(w[:-1] + "య")) for n, w in TE_TENS.items())
_TE_VOWEL_OF = {"ొ": "ఒ", "ై": "ఐ", "ా": "ఆ", "ె": "ఎ"}


def _te_base(stem: str) -> _Lex | None:
    """The cardinal a sandhi stem came from: ఐద -> ఐదు, ఎనిమిద -> ఎనిమిది."""
    for end in _TE_VOWEL_ENDS:
        lex = _LEX.get(stem + end)
        if lex is not None and lex.kind == "num" and lex.te and not lex.weak and lex.unit == 1:
            if isinstance(lex.n, int):
                return lex
    return None


def _te_lookup(k: str) -> _Lex | None:
    """Telugu words the lexicon cannot list: inflected stems and numbers with a fused suffix."""
    for stem, lex in _TE_STEMS:
        if k.startswith(stem):
            return lex
    for stem, lex in _TE_SCALE_STEMS:
        if k.startswith(stem) and _TE_CASE.fullmatch(k, len(stem)):
            return lex
    if k.endswith(_TE_HALF):
        stem = k[: -len(_TE_HALF)]
        whole = _LEX.get(stem)
        if whole is not None and whole.kind == "scale" and whole.bare:  # లక్షన్నర
            return _Lex("num", Fraction(3, 2) * whole.n, te=True, unit=int(whole.n))
        if (base := _te_base(stem)) is not None:  # రెండున్నర
            return _Lex("num", base.n + Fraction(1, 2), te=True)
    for suffix in _TE_QUARTER:
        if k.endswith(suffix) and (base := _te_base(k[: -len(suffix)])) is not None:  # రెండుంపావు
            return _Lex("num", base.n + Fraction(1, 4), te=True)
    for suffix in _TE_HUNDREDS:
        if k.endswith(suffix) and (base := _te_base(k[: -len(suffix)])) is not None and 2 <= base.n <= 9:
            return _Lex("num", base.n * 100, te=True, unit=100)  # రెండొందలు
    for suffix in _TE_ORDINAL:
        if k.endswith(suffix) and (base := _te_base(k[: -len(suffix)])) is not None and 1 <= base.n <= 31:
            return _Lex("num", base.n, te=True)  # పదిహేనో, పదిహేనవ
    for tens, stem in _TE_TENS_STEMS:  # sandhi of ten and unit: డెబ్బయైదు, ఇరవయ్యొకటి, ముప్పయ్యారు
        if k.startswith(stem) and len(k) > len(stem) and k[len(stem)] in _TE_VOWEL_OF:
            unit_word = _TE_VOWEL_OF[k[len(stem)]] + k[len(stem) + 1 :]
            unit = _LEX.get(unit_word) or _te_lookup(unit_word)
            if unit is not None and unit.kind == "num" and unit.te and unit.unit == 1 and 1 <= unit.n <= 9:
                return _Lex("num", tens + unit.n, te=True)
    for suffix in _TE_FUSED:
        if k.endswith(suffix) and len(k) > len(suffix):
            base = _LEX.get(k[: -len(suffix)])
            if base is not None and base.kind == "num" and not base.weak:
                return base
    return None


_TE_JOINABLE: frozenset[_Kind] = frozenset({"num", "scale", "cur", "date"})


def _te_split(word: str, depth: int = 3) -> list[tuple[int, _Lex]] | None:
    """(end offset, entry) per part of a number written as one word: రెండువేల, ఇరవైఐదు, పదివేలరూపాయలు."""
    if depth == 0:
        return None
    for k in range(len(word) - 1, 0, -1):
        if unicodedata.category(word[k]) in ("Mn", "Mc"):
            continue  # never cut inside a syllable
        left = _lookup(word[:k])
        if left is None or left.kind not in ("num", "scale"):
            continue
        right = _lookup(word[k:])
        if right is not None and right.kind in _TE_JOINABLE:
            return [(k, left), (len(word), right)]
        rest = _te_split(word[k:], depth - 1)
        if rest is not None:
            return [(k, left), *((k + end, lex) for end, lex in rest)]
    return None


# ---------------------------------------------------------------- tokens

_TOKEN = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+(?!,?\d)|\d{1,3}(?:,\d{2})*,\d{3}(?!,?\d)|\d+(?:\.\d+)?)"
    r"(?P<suf>(?:k|K|st|nd|rd|th)(?![A-Za-z])|थ(?![ऀ-ॿ])|వ(?![ఀ-౿]))?"
    r"|(?P<word>[A-Za-z̀-ͯऀ-ॣॱ-ॿఀ-౥౰-౿‌‍']+)"
    r"|(?P<sym>₹)"
)
_GLUE = re.compile(r"[\s,\-–—/+]*")  # may sit inside one spoken number or digit run
_PREV_CUE_GAP = re.compile(r"[\s.:\-]*")
# "15थ": a recogniser writing "15th" in Devanagari. "17వ": the Telugu ordinal ending on a written number.
_ORD_SUFFIX = ("st", "nd", "rd", "th", "थ", "వ")
_CUE_TAIL = r"[\s:.,\-]*(?:(?:है|hai|is|इज़?|इस|का|ka|की|ki)[\s:.,\-]*)*$"
# Only a spoken label makes a digit run a PIN or an account: bare, it stays what it always was.
_PIN_CUE = re.compile(
    r"(?:pin\s*code|pincode|postal\s*code|पिन\s*कोड|पिनकोड|పిన్\s*కోడ్|పిన్‌కోడ్)" + _CUE_TAIL, re.IGNORECASE
)
_ACCOUNT_CUE = re.compile(
    r"(?:account|acct|a/c|khata|khaata|खाता|खाते|अकाउंट|अकाउन्ट|एकाउंट|ఖాతా|అకౌంట్)"
    r"(?:\s*(?:number|num|no\.?|nambar|नंबर|नम्बर|నంబర్|నెంబర్))?" + _CUE_TAIL,
    re.IGNORECASE,
)
_CUE_WINDOW = 48
_MIN_CUED_DIGITS: dict[Slot, int] = {"pincode": 4, "account_number": 6}


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
    te: bool = False
    bare: bool = False
    unit: int = 1


_DEV_PREFIX = tuple((_dev_key(p), _Lex("scale", n)) for p, n in (("थाउ", 1000), ("हंड्र", 100)))
_ORD_TAIL = re.compile("(?:ि?[एय]|इ)?्?थ्?$")


def _lookup(word: str) -> _Lex | None:
    k = _key(word)
    if (lex := _LEX.get(k)) is not None:
        return lex
    if _TEL_RE.search(word):
        return _te_lookup(k)
    if not _DEV_RE.search(word):
        return None
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
            word = m.group("word")
            lex = _lookup(word)
            parts = [(len(word), lex)] if lex is not None else None
            if parts is None and _TEL_RE.search(word):
                parts = _te_split(word)
            if parts is None:
                out.append(_Tok(None, s, e))
                continue
            at = s
            for end, lx in parts:
                out.append(
                    _Tok(lx.kind, at, s + end, Fraction(lx.n), lx.word, lx.en, lx.weak,
                         te=lx.te, bare=lx.bare, unit=lx.unit)
                )  # fmt: skip
                at = s + end
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
            if t.te:
                return self.small_te(i)
            return t.num, i + 1
        if t.kind == "un" and j is not None:
            u = self.toks[j]
            if u.kind == "num" and not u.en and not u.lit and u.num in _TENS:
                return u.num - 1, j + 1
        if t.kind == "a" and (sc := self.scale(j)) is not None and not sc.weak:
            return Fraction(1), i + 1
        return None

    def small_te(self, i: int) -> _Span | None:
        """ఇరవై ఐదు, ఇరవై రెండున్నర, రెండు ముప్పావు: ten, unit and quarter are separate words."""
        t = self.toks[i]
        n, end = t.num, i + 1
        if n in _TENS and (j := self.nx(i)) is not None:
            u = self.toks[j]
            if u.kind == "num" and u.te and not u.weak and u.unit == 1 and 1 <= u.num < 10:
                n, end = n + u.num, j + 1
        if n.denominator == 1 and n >= 1 and (j := self.nx(end - 1)) is not None:
            u = self.toks[j]
            if u.kind == "num" and u.te and u.weak and 0 < u.num < 1:
                n, end = n + u.num, j + 1
        # Part of a scale is an amount only with the scale after it; alone it is an ordinary word.
        if n.denominator != 1 and not self.scale(self.nx(end - 1)):
            return None
        return n, end

    def term(self, i: int, cont: bool) -> tuple[Fraction, int, int, bool] | None:
        """(value, unit, next index, used a fraction idiom)."""
        t = self.toks[i]
        if t.kind == "num" and t.unit > 1:
            return t.num, t.unit, i + 1, False
        if t.kind == "scale" and t.bare:
            return t.num, int(t.num), i + 1, False
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
        if t.kind == "scale" and not (t.weak or t.te or cont) and self.kind(self.nx(i)) == "cur":
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

    def digit_run(self, i: int) -> list[tuple[str, int]]:
        """(digits, end index) for each piece of the digit run starting at token i."""
        if i > 0 and self.kind(i - 1) == "cur" and self.toks[i].lit:
            return []
        parts: list[tuple[str, int]] = []
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
                if r is None:  # a Telugu number that needs a scale after it (ఆరు అర) ends the run
                    break
                parts.append((str(int(r[0])), r[1]))
                k = self.nx(r[1] - 1)
            j = k
        while parts and self.kind(self.nx(parts[-1][1] - 1)) in ("scale", "date", "cur", "frac"):
            parts.pop()
        return parts

    def cued_digits(self, i: int) -> tuple[Slot, str, int] | None:
        """A digit run right after a spoken "PIN code" or "account number" label."""
        if self.toks[i].kind not in ("num", "rep"):
            return None
        start = self.toks[i].start
        before = self.text[max(0, start - _CUE_WINDOW) : start]
        slot: Slot | None = (
            "pincode"
            if _PIN_CUE.search(before)
            else "account_number"
            if _ACCOUNT_CUE.search(before)
            else None
        )
        if slot is None:
            return None
        parts = self.digit_run(i)
        digits = "".join(p for p, _ in parts)
        return (slot, digits, parts[-1][1]) if len(digits) >= _MIN_CUED_DIGITS[slot] else None

    def phone(self, i: int) -> tuple[str, int] | None:
        parts = self.digit_run(i)
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
            if (c := self.cued_digits(i)) is not None:
                out.append(self.entity(c[0], c[1], i, c[2]))
                i = c[2]
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


def small_numbers(text: str) -> list[int]:
    """Every standalone number below 100 in the text, for short answers like "saat" to a forced choice."""
    return [
        int(t.num)
        for t in _Parser(text).toks
        if t.kind == "num" and t.num.denominator == 1 and t.num < 100 and (t.en or not t.weak)
    ]


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
