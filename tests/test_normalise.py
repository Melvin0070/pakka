from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from pramaan.lexicon import HI_0_99
from pramaan.normalise import extract, parse_number, values
from pramaan.render import (
    amount_renderings,
    english_day_renderings,
    hindi_cardinal,
    phone_renderings,
    renderings,
)

G0 = Path(__file__).resolve().parents[1] / "g0"
PROMPTS = json.loads((G0 / "prompts.json").read_text())

A, D, W, P = "amount_rupees", "day_of_month", "weekday", "phone"

# Correct Devanagari transcripts of g0/prompts.json, as a careful human would write them.
G0_DEVANAGARI = {
    "a01": "अगले मंगलवार को पौने तीन हज़ार रुपये दे दूँगा।",
    "a02": "सवा दो लाख का पेमेंट पच्चीस तारीख को हो जाएगा।",
    "a03": "अभी ढाई हज़ार भेज रहा हूँ, बाकी शुक्रवार को।",
    "a04": "डेढ़ लाख रुपये इक्कीस तारीख तक पक्का।",
    "a05": "साढ़े सात सौ रुपये COD है, कैश रेडी रखना।",
    "a06": "टोटल पचपन सौ बनता है, सोमवार को ट्रांसफर करूँगा।",
    "a07": "उन्नीस हज़ार पाँच सौ का ईएमआई है, तीन तारीख को कटेगा।",
    "a08": "उनतालीस हज़ार रुपये बुधवार को दे दूँगा।",
    "a09": "उनसठ हज़ार का चेक गुरुवार को मिलेगा।",
    "a10": "I will pay fifteen thousand on the fifteenth.",
    "a11": "फिफ्टी थाउजंड का पेमेंट सत्रह तारीख को आएगा।",
    "a12": "सत्रह हज़ार रुपये शनिवार तक भेज दूँगा।",
    "a13": "सत्तर हज़ार का बैलेंस है, सत्ताईस तारीख को क्लियर।",
    "a14": "साढ़े बारह हज़ार का बिल है सर।",
    "a15": "पौने दो सौ रुपये डिलीवरी चार्ज लगेगा।",
    "a16": "सवा तीन सौ का रिचार्ज कर देना, रविवार से पहले।",
    "a17": "एक लाख बीस हज़ार उनतीस तारीख को दूँगा।",
    "a18": "पचहत्तर सौ रुपये एडवांस, बाकी मंगलवार को।",
    "a19": "तीन हज़ार तीन सौ तीस रुपये का ऑर्डर है।",
    "a20": "चौरानवे हज़ार का लोन अमाउंट है, उन्नीस तारीख को ड्यू।",
    "a21": "नौ हज़ार नौ सौ निन्यानवे का फ़ोन है, ईएमआई पे।",
    "a22": "थर्टीन हंड्रेड रुपीज़, I'll send it on the thirtieth.",
    "a23": "ढाई लाख का डाउन पेमेंट बुधवार को करेंगे।",
    "a24": "छह हज़ार छह सौ साठ रुपये, छब्बीस तारीख को।",
    "p01": "मेरा नंबर नोट करो: नाइन एट डबल फ़ोर, सेवन वन टू, ट्रिपल ज़ीरो।",
    "p02": "इस नंबर पे कॉल करना: सात ज़ीरो नौ दो, तीन तीन, चार एक पाँच छह।",
    "p03": "कॉलबैक नंबर है डबल नाइन एट सिक्स, ज़ीरो फ़ाइव वन, दो दो सात।",
    "p04": "आठ तीन एक एक, नौ ज़ीरो, सात छह पाँच चार पे फ़ोन करो, साढ़े चार हज़ार के बारे में।",
    "p05": "माय नंबर इज़ सिक्स थ्री डबल ज़ीरो, वन नाइन एट, फ़ोर सेवन टू।",
    "p06": "नौ चार ट्रिपल वन, आठ दो, सात तीन ज़ीरो पे शुक्रवार को कॉल करना।",
}


@pytest.mark.parametrize("p", PROMPTS, ids=lambda p: p["id"])
def test_g0_roman(p: dict) -> None:
    assert values(p["say"]) == p["truth"]


@pytest.mark.parametrize("p", PROMPTS, ids=lambda p: p["id"])
def test_g0_devanagari(p: dict) -> None:
    assert values(G0_DEVANAGARI[p["id"]]) == p["truth"]


CASES: list[tuple[str, dict]] = [
    # Hindi cardinals, Devanagari, with spelling variance
    ("पाँच सौ रुपये", {A: 500}),
    ("पांच सौ रुपये", {A: 500}),
    ("छह सौ", {A: 600}),
    ("छः सौ", {A: 600}),
    ("छे सौ रुपए", {A: 600}),
    ("दो सो रुपये", {A: 200}),
    ("तीन हजार", {A: 3000}),
    ("तीन हज़ार", {A: 3000}),
    ("उनतालीस हजार", {A: 39000}),
    ("उन्तालीस हजार", {A: 39000}),
    ("चवालीस हज़ार", {A: 44000}),
    ("चौवालीस हज़ार", {A: 44000}),
    ("छियासी हज़ार", {A: 86000}),
    ("नवासी हज़ार", {A: 89000}),
    ("उन्यासी हज़ार", {A: 79000}),
    ("उनासी हज़ार", {A: 79000}),
    ("अड़तालिस हज़ार", {A: 48000}),
    ("अडतालीस हज़ार", {A: 48000}),
    ("पन्द्रह सौ", {A: 1500}),
    ("पंद्रह सौ", {A: 1500}),
    ("चौरनवे हजार", {A: 94000}),
    ("चॉरनवे हजार", {A: 94000}),
    ("उन चालीस हज़ार रुपये", {A: 39000}),
    ("उनत्तीस तारीख", {D: 29}),
    ("एक करोड़ रुपये", {A: 10_000_000}),
    ("दो करोड़ पचास लाख", {A: 25_000_000}),
    ("एक लाख एक", {A: 100_001}),
    ("सात लाख सत्तर हज़ार सात सौ सात", {A: 770_707}),
    ("निन्यानवे लाख निन्यानवे हज़ार नौ सौ निन्यानवे", {A: 9_999_999}),
    ("एक सौ एक रुपये", {A: 101}),
    ("ग्यारह सौ", {A: 1100}),
    ("शून्य रुपये", {A: 0}),
    # Hindi cardinals, Roman
    ("paanch sau rupaye", {A: 500}),
    ("panch sau", {A: 500}),
    ("chhe hazaar", {A: 6000}),
    ("che hazar", {A: 6000}),
    ("chhah hajar", {A: 6000}),
    ("teen hajaar", {A: 3000}),
    ("pachpan sau", {A: 5500}),
    ("unnis hazaar", {A: 19000}),
    ("untalis hazaar", {A: 39000}),
    ("unchaas hazaar", {A: 49000}),
    ("chauranve hazaar", {A: 94000}),
    ("ninyaanve rupaye", {A: 99}),
    ("satattar hazaar", {A: 77000}),
    ("pachattar sau", {A: 7500}),
    ("pachhattar sau", {A: 7500}),
    ("athasi hazaar", {A: 88000}),
    ("do lakh", {A: 200_000}),
    ("do lac", {A: 200_000}),
    ("ek crore", {A: 10_000_000}),
    ("barah sau", {A: 1200}),
    ("das hazaar paanch sau", {A: 10_500}),
    ("ek lakh aur bees hazaar", {A: 120_000}),
    ("sattaees hazaar", {A: 27_000}),
    ("sattais hazar", {A: 27_000}),
    # Fraction idioms
    ("paune teen hazaar", {A: 2750}),
    ("pone teen hazar", {A: 2750}),
    ("sava do lakh", {A: 225_000}),
    ("sawa do lakh", {A: 225_000}),
    ("saadhe barah hazaar", {A: 12_500}),
    ("sadhe barah hazar", {A: 12_500}),
    ("saade barah hazar", {A: 12_500}),
    ("paune do sau", {A: 175}),
    ("dedh lakh", {A: 150_000}),
    ("derh lakh", {A: 150_000}),
    ("dhai hazaar", {A: 2500}),
    ("adhai hazaar", {A: 2500}),
    ("dedh sau", {A: 150}),
    ("sava sau", {A: 125}),
    ("dhai sau", {A: 250}),
    ("paune sau rupaye", {A: 75}),
    ("sava lakh", {A: 125_000}),
    ("saadhe saat sau", {A: 750}),
    ("साढ़े सात सौ", {A: 750}),
    ("साढे सात सौ", {A: 750}),
    ("सवा करोड़", {A: 12_500_000}),
    ("सावा दो लाख", {A: 225_000}),
    ("पौने दो लाख", {A: 175_000}),
    ("डेढ़ हज़ार", {A: 1500}),
    ("डेढ हजार", {A: 1500}),
    ("ढाई सौ", {A: 250}),
    ("अढ़ाई हज़ार", {A: 2500}),
    ("ek lakh sava do hazaar", {A: 102_250}),
    ("saadhe teen baje", {}),  # time, not money
    # English and mixed
    ("fifteen hundred rupees", {A: 1500}),
    ("thirteen hundred", {A: 1300}),
    ("one lakh twenty thousand", {A: 120_000}),
    ("fifty thousand", {A: 50_000}),
    ("twenty five thousand", {A: 25_000}),
    ("twenty-five thousand", {A: 25_000}),
    ("one hundred and twenty five rupees", {A: 125}),
    ("two hundred fifty thousand", {A: 250_000}),
    ("a hundred rupees", {A: 100}),
    ("a thousand", {A: 1000}),
    ("fifty rupees", {A: 50}),
    ("ninety nine thousand nine hundred ninety nine", {A: 99_999}),
    ("फिफ्टी थाउजंड", {A: 50_000}),
    ("टू थाउज़ेंड फ़ाइव हंड्रेड", {A: 2500}),
    ("do lakh fifty thousand", {A: 250_000}),
    ("fifty hazaar", {A: 50_000}),
    # Digits
    ("2,750", {A: 2750}),
    ("₹2750", {A: 2750}),
    ("₹ 2,750", {A: 2750}),
    ("Rs. 2,25,000", {A: 225_000}),
    ("Rs 50", {A: 50}),
    ("INR 1,000,000", {A: 1_000_000}),
    ("2.5 lakh", {A: 250_000}),
    ("12.5k", {A: 12_500}),
    ("15k", {A: 15_000}),
    ("2 lakh 50 hazaar", {A: 250_000}),
    ("२७५० रुपये", {A: 2750}),
    ("500 rupaye", {A: 500}),
    ("50 ka recharge", {A: 50}),
    # Phones
    ("nine eight double four seven one two triple zero", {P: "9844712000"}),
    ("double nine eight six zero five one do do saat", {P: "9986051227"}),
    ("डबल नाइन एट सिक्स ज़ीरो फाइव वन दो दो सात", {P: "9986051227"}),
    ("नौ चार ट्रिपल वन आठ दो सात तीन ज़ीरो", {P: "9411182730"}),
    ("सात शून्य नौ दो तीन तीन चार एक पाँच छः", {P: "7092334156"}),
    ("98440 12345", {P: "9844012345"}),
    ("98440-12345", {P: "9844012345"}),
    ("9844012345", {P: "9844012345"}),
    ("+91 98440 12345", {P: "9844012345"}),
    ("+91-9844012345", {P: "9844012345"}),
    ("098440 12345", {P: "9844012345"}),
    ("zero nine eight four four zero one two three four five", {P: "9844012345"}),
    ("ninety eight forty four seventy one twenty three four five", {P: "9844712345"}),
    ("nine eight four four seven one two zero zero", {P: "984471200"}),  # malformed: 9 digits, raw
    ("one two three four five six seven eight nine zero", {P: "1234567890"}),  # malformed: starts with 1
    ("nine eight four four", {}),
    ("saat teen zero nau aath, do sau rupaye", {A: 200}),  # 5 digits: not a phone
    ("nine eight four four seven one two zero zero zero, do sau rupaye", {P: "9844712000", A: 200}),
    ("₹98440000", {A: 98_440_000}),
    # Day of month
    ("pachees tareekh ko", {D: 25}),
    ("pachchis tarikh", {D: 25}),
    ("3 tareekh", {D: 3}),
    ("teen tareekh ko", {D: 3}),
    ("तीस तारीख़", {D: 30}),
    ("on the fifteenth", {D: 15}),
    ("fifteenth", {D: 15}),
    ("30th", {D: 30}),
    ("the thirtieth", {D: 30}),
    ("twenty first ko", {D: 21}),
    ("on the first", {D: 1}),
    ("first time", {}),
    ("one second", {}),
    ("chalis tareekh", {}),  # not a day, and not an amount either
    ("ek lakh bees hazaar unattees tareekh", {A: 120_000, D: 29}),
    ("do hazaar pachees tareekh ko", {A: 2000, D: 25}),
    ("5 tareekh ko 500 rupaye", {D: 5, A: 500}),
    # Weekdays
    ("somvaar ko", {W: "monday"}),
    ("Monday", {W: "monday"}),
    ("मंगल को", {W: "tuesday"}),
    ("mangal ko", {W: "tuesday"}),
    ("mangalwar", {W: "tuesday"}),
    ("budhvaar", {W: "wednesday"}),
    ("guruvaar", {W: "thursday"}),
    ("brihaspativaar", {W: "thursday"}),
    ("बृहस्पतिवार", {W: "thursday"}),
    ("veervaar", {W: "thursday"}),
    ("shukrawar", {W: "friday"}),
    ("shanivaar", {W: "saturday"}),
    ("ravivaar", {W: "sunday"}),
    ("itvaar", {W: "sunday"}),
    ("इतवार", {W: "sunday"}),
    # Disambiguation
    ("ek call kar dena", {}),
    ("do din baad", {}),
    ("mere saath chalo", {}),
    ("मेरे साथ", {}),
    ("chhe sau saath rupaye", {A: 660}),
    ("saath hazaar", {A: 60_000}),
    ("saat hazaar", {A: 7000}),
    ("सो जाओ", {}),
    ("so I will pay", {}),
    ("ek rupaya", {A: 1}),
    ("पचास का रिचार्ज", {A: 50}),
    ("उन लोगों को सौ रुपये दो", {A: 100}),
    # English spoken, written in Devanagari (VerbX, Hindi acoustic models)
    ("मेरा नंबर नोट करो नाइन एट डबल फोर सैवन वन टू ट्रिपल ज़ीरो", {P: "9844712000"}),
    ("आई विल पे फिफ्टीन थाउज़ेंड ऑन द फिफ्टींथ", {A: 15_000, D: 15}),
    ("फिफ्टीन थाउजेंड ऑन द फिफ्टीनथ", {A: 15_000, D: 15}),
    ("थर्टीन हंड्रेड रुपीज़", {A: 1300}),
    ("टू थाउजेंऑ फाइव हंड्रेड", {A: 2500}),
    ("वन लाख ट्वेंटी थाउसेंड", {A: 120_000}),
    ("नाइंटी नाइन थाउज़ेंड नाइन हंड्रेड नाइनटी नाइन", {A: 99_999}),
    ("सेवेंटी फाइव हंड्रेड", {A: 7500}),
    ("फिफ्टी रुपीज़", {A: 50}),
    ("वन हंड्रेड एंड ट्वेंटी फाइव", {A: 125}),
    ("नाईन एइट फ़ोर फ़ोर सेवेन वन टु थ्री फोर फ़ाइव", {P: "9844712345"}),
    ("नाइन एट ओ ओ सेवन वन टू थ्री फोर फाइव", {P: "9800712345"}),
    ("nine eight double oh seven one two three four five", {P: "9800712345"}),
    ("ओ भाई", {}),
    ("ऑन द थर्टिएथ", {D: 30}),
    ("द ट्वेंटी सेवंथ", {D: 27}),
    ("ट्वेंटी फर्स्ट को", {D: 21}),
    ("फोर्थ तारीख", {D: 4}),
    ("ऑन द फर्स्ट", {D: 1}),
    ("वन सेकंड", {}),
    ("सिक्स्थ", {D: 6}),
    ("एट्थ", {D: 8}),
    ("मंडे को", {W: "monday"}),
    ("ट्यूज़डे", {W: "tuesday"}),
    ("ट्यूसडे", {W: "tuesday"}),
    ("थुस्डे", {W: "tuesday"}),
    ("वेडनेसडे", {W: "wednesday"}),
    ("वेंसडे", {W: "wednesday"}),
    ("वेनस्डे", {W: "wednesday"}),
    ("थर्सडे", {W: "thursday"}),
    ("थर्स्डे", {W: "thursday"}),
    ("फ्राइडे", {W: "friday"}),
    ("फ़्राइडे", {W: "friday"}),
    ("सैटरडे", {W: "saturday"}),
    ("सैटर्डे", {W: "saturday"}),
    ("संडे", {W: "sunday"}),
    ("ऑन फ्राइडे आई विल पे फाइव थाउज़ेंड", {W: "friday", A: 5000}),
]


def test_case_table_size() -> None:
    assert len(CASES) >= 120


@pytest.mark.parametrize(("text", "expected"), CASES, ids=[c[0] for c in CASES])
def test_cases(text: str, expected: dict) -> None:
    assert values(text) == expected
    for e in extract(text):
        assert text[e.start : e.end] == e.text


def test_spans_exclude_cue_words() -> None:
    (e,) = extract("Rs. 2,25,000 bhejo")
    assert e.text == "2,25,000"
    a, d = extract("सवा दो लाख रुपये पच्चीस तारीख को")
    assert (a.text, d.text) == ("सवा दो लाख", "पच्चीस")
    (p,) = extract("call +91 98440-12345 pe")
    assert p.text == "91 98440-12345"


def test_values_takes_first_amount() -> None:
    assert values("paanch sau rupaye abhi, baaki do hazaar")[A] == 500
    assert [e.value for e in extract("paanch sau rupaye abhi, baaki do hazaar")] == [500, 2000]


@pytest.mark.parametrize(
    ("text", "n"),
    [("paune teen hazaar", 2750), ("2,25,000", 225_000), ("fifteen hundred rupees", 1500), ("सात", 7),
     ("nine eight", None), ("hello", None), ("saadhe teen", None), ("1.5", None)],
)  # fmt: skip
def test_parse_number(text: str, n: int | None) -> None:
    assert parse_number(text) == n


# ---------------------------------------------------------------- properties against render.py


def _renderings_or_skip(n: int) -> list[str]:
    try:
        return amount_renderings(n)
    except IndexError:
        assume(False)  # render bug, see test_render_paune_overflow
        raise


@settings(max_examples=400)
@given(st.integers(1, 99_99_999))
def test_amount_renderings_round_trip(n: int) -> None:
    for r in _renderings_or_skip(n):
        assert parse_number(r) == n, r
        assert values(f"{r} रुपये दे दूँगा")[A] == n, r


@settings(max_examples=400)
@given(st.integers(1, 99_99_999))
def test_all_amount_renderings_round_trip(n: int) -> None:
    try:
        forms = renderings("amount_rupees", n)
    except IndexError:
        assume(False)  # render bug, see test_render_paune_overflow
        raise
    for r in forms:
        assert parse_number(r) == n, r
        assert values(f"{r} रुपीज़")[A] == n, r


@pytest.mark.parametrize("d", range(1, 32))
def test_all_day_renderings_round_trip(d: int) -> None:
    for r in renderings("day_of_month", d):
        assert values(f"{r} तारीख को") == {D: d}, r
    for r in english_day_renderings(d):
        assert values(f"ऑन द {r}") == {D: d}, r


@pytest.mark.parametrize(
    "day", ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
)
def test_all_weekday_renderings_round_trip(day: str) -> None:
    for r in renderings("weekday", day):
        text = f"अगले {r} को पाँच सौ रुपये"
        (w, a) = extract(text)
        assert (w.slot, w.value, a.value) == (W, day, 500), r
        assert text[w.start : w.end] == w.text == r


@pytest.mark.parametrize("n", [125, 150, 175, 250, 1250, 1500, 2750, 5500, 12_500, 225_000, 9_975_000 - 250])
def test_amount_renderings_fixed(n: int) -> None:
    for r in amount_renderings(n):
        assert parse_number(r) == n, r


@pytest.mark.xfail(raises=IndexError, reason="render._fraction_forms: paune with k=99 indexes HI_0_99[100]")
def test_render_paune_overflow() -> None:
    amount_renderings(99_750)


@settings(max_examples=300)
@given(st.integers(0, 10**7))
def test_hindi_cardinal_round_trip(n: int) -> None:
    assert parse_number(hindi_cardinal(n)) == n


phones = st.builds(lambda h, t: h + t, st.sampled_from("6789"), st.text("0123456789", min_size=9, max_size=9))


@settings(max_examples=300)
@given(phones)
def test_phone_renderings_round_trip(d: str) -> None:
    for r in phone_renderings(d):
        assert values(r) == {P: d}, r
        assert values(f"मेरा नंबर {r} है, शुक्रवार को कॉल करना") == {P: d, W: "friday"}, r


@settings(max_examples=300)
@given(
    st.integers(100, 99_99_999),
    st.integers(100, 99_99_999),
    st.sampled_from(["", "अगले मंगलवार को ", "total "]),
    st.sampled_from(["रुपये", "rupaye", "का पेमेंट"]),
    st.data(),
)
def test_amount_span_swap(n: int, m: int, prefix: str, cue: str, data: st.DataObject) -> None:
    r = data.draw(st.sampled_from(_renderings_or_skip(n)))
    r2 = data.draw(st.sampled_from(_renderings_or_skip(m)))
    text = f"{prefix}{r} {cue} पच्चीस तारीख को"
    *_, e, d = extract(text)
    assert (e.slot, e.value, d.value) == (A, n, 25)
    assert text[e.start : e.end] == e.text == r
    swapped = text[: e.start] + r2 + text[e.end :]
    assert values(swapped) == {**values(prefix), A: m, D: 25}


@settings(max_examples=200)
@given(phones, phones, st.data())
def test_phone_span_swap(d1: str, d2: str, data: st.DataObject) -> None:
    r = data.draw(st.sampled_from(phone_renderings(d1)))
    r2 = data.draw(st.sampled_from(phone_renderings(d2)))
    text = f"मेरा नंबर {r} पे साढ़े चार हज़ार के बारे में कॉल करना"
    p, a = extract(text)
    assert (p.value, a.value) == (d1, 4500)
    assert text[p.start : p.end] == r
    assert values(text[: p.start] + r2 + text[p.end :]) == {P: d2, A: 4500}


@given(st.integers(1, 31), st.integers(1, 31))
def test_day_span_swap(a: int, b: int) -> None:
    text = f"दो हज़ार रुपये {HI_0_99[a]} तारीख को"
    _, d = extract(text)
    assert (d.slot, d.value) == (D, a)
    assert values(text[: d.start] + HI_0_99[b] + text[d.end :]) == {A: 2000, D: b}


@given(st.text(alphabet="एक दो सौ हज़ार साथ सो तारीख रुपये, ₹0123456789.kthsavadhai", max_size=60))
def test_never_crashes_and_spans_hold(text: str) -> None:
    for e in extract(text):
        assert text[e.start : e.end] == e.text
        if e.slot == D:
            assert 1 <= int(e.value) <= 31


# ---------------------------------------------------------------- real ASR transcripts

# The ASR text is wrong in these clips; the expected value is the literal reading of what it wrote.
ASR_ERRORS: dict[str, dict] = {
    "ttsalloy_a08_clean|B": {A: 48_000, W: "wednesday"},  # अड़तालिस (48) for untalis (39)
    "ttsalloy_a08_phone|B": {A: 48_000, W: "wednesday"},
    "ttsonyx_a08_phone|B": {A: 43_000, W: "wednesday"},  # "उन तैंतालीस": un + 43
    "ttsalloy_a09_clean|B": {A: 7000, W: "thursday"},  # "उन सात": saat (7) for unsath (59)
    "ttsalloy_a09_phone|B": {A: 7000, W: "thursday"},
    "ttsonyx_a09_clean|B": {A: 7000, W: "thursday"},
    "ttsonyx_a09_phone|B": {A: 7000, W: "thursday"},
    "ttsalloy_a24_clean|B": {A: 6607, D: 26},  # सात (7) for saath (60)
    "ttsalloy_a24_phone|B": {A: 6607, D: 26},
    "ttsonyx_a24_clean|B": {A: 6607, D: 26},
    "ttsonyx_a24_phone|B": {A: 6607, D: 26},
    "ttsonyx_p04_phone|B": {P: "7311907654", A: 4500},  # सात for aath in the first digit
}

_results_path = G0 / "results.json"
TRANSCRIPTS = (
    {k: v["_transcript"] for k, v in json.loads(_results_path.read_text()).items() if "_transcript" in v}
    if _results_path.exists()
    else {}
)
TRUTH = {p["id"]: p["truth"] for p in PROMPTS}


@pytest.mark.skipif(not TRANSCRIPTS, reason="no g0/results.json")
@pytest.mark.parametrize("key", sorted(TRANSCRIPTS))
def test_asr_transcripts(key: str) -> None:
    expected = ASR_ERRORS.get(key, TRUTH[key.split("_")[1]])
    assert values(TRANSCRIPTS[key]) == expected, TRANSCRIPTS[key]


@pytest.mark.parametrize(
    ("text", "day"),
    [("आई विल ट्रांसफर इट ऑन द २८।", 28), ("इट ऑन द 15थ।", 15), ("इट ऑन द सेवेनटीन।", 17), ("on the 7", 7)],
)
def test_english_dates_as_recognisers_write_them(text: str, day: int) -> None:
    assert [(e.slot, e.value) for e in extract(text)] == [("day_of_month", day)]


def test_on_the_does_not_turn_an_amount_or_a_count_into_a_date() -> None:
    assert [(e.slot, e.value) for e in extract("I will pay on the 5 thousand")] == [("amount_rupees", 5000)]
    assert extract("the 5 options") == [] and extract("on the 45") == []
