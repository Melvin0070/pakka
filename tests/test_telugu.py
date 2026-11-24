"""Telugu: the renderer and the parser must be inverses, and the Hindi settings must not have moved."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pakka import confusables, lang
from pakka.cache import params_sha
from pakka.lexicon import TE_0_99, WEEKDAYS
from pakka.normalise import parse_number, values
from pakka.render import renderings, telugu_amount_renderings, telugu_cardinal, telugu_ordinal
from pakka.sources import gpt4o_transcribe, gpt_transcribe, realtime_agent, saaras, verbx
from pakka.witness import Pieces, build_graph, phone_edges


@given(st.integers(1, 99_99_99_999))
@settings(max_examples=400)
def test_every_amount_rendering_parses_back(n):
    for r in telugu_amount_renderings(n):
        assert parse_number(r) == n, r
        assert values(f"{r} రూపాయలు") == {"amount_rupees": n}, r


@pytest.mark.parametrize(
    ("text", "n"),
    [
        ("వంద", 100), ("నూట యాభై", 150), ("వెయ్యి ఐదు వందలు", 1500), ("పదిహేను వందలు", 1500),
        ("రెండున్నర వేలు", 2500), ("లక్షన్నర", 150_000), ("ఒకటిన్నర లక్షలు", 150_000),
        ("రెండుంపావు లక్షలు", 225_000), ("రెండు ముప్పావు లక్షలు", 275_000), ("ముప్పావు లక్ష", 75_000),
        ("అర లక్ష", 50_000), ("ఇరవై రెండున్నర వేలు", 22_500), ("రెండొందల యాభై", 250),
        ("రెండువేల ఐదువందలు", 2500), ("ఇరవైఐదు వేలు", 25_000), ("ఒక లక్ష", 100_000), ("కోటి", 10_000_000),
        ("ట్వంటీ ఫైవ్ థౌజండ్", 25_000), ("iravai aidu velu", 25_000), ("2.5 లక్షలు", 250_000),
    ],
)  # fmt: skip
def test_amount_idioms(text, n):
    assert parse_number(text) == n


@pytest.mark.parametrize("d", range(1, 32))
def test_day_of_month(d):
    for form in telugu_ordinal(d):
        assert values(f"{form} తేదీన ఇస్తాను") == {"day_of_month": d}
    assert values(f"{d}వ తేదీకి") == {"day_of_month": d}
    assert values(f"{TE_0_99[d]} తారీఖున") == {"day_of_month": d}


@pytest.mark.parametrize("day", WEEKDAYS)
def test_weekdays_with_case_endings(day):
    for r in renderings("weekday", day, "te"):
        assert values(r) == {"weekday": day}
    stem = renderings("weekday", day, "te")[0][:-1]
    assert values(f"{stem}ానికి ఇస్తాను") == {"weekday": day}


@given(st.from_regex(r"[6-9][0-9]{9}", fullmatch=True))
def test_phone_renderings_parse_back(digits):
    for r in renderings("phone", digits, "te"):
        assert values(f"నా నంబర్ {r}") == {"phone": digits}


def test_recogniser_habits():
    assert values("సిక్స్ టూ సెవెన్ ఎయిట్ వన్ ఎయిట్ సిక్స్ సిక్స్ టూ జీరోకి ఫోన్ చేయండి") == {"phone": "6278186620"}
    assert values("లోన్‌లో 47,500 రూపాయలు బాకీ ఉంది. 17వ తేదీన క్లియర్ చేస్తాను.") == {
        "amount_rupees": 47500,
        "day_of_month": 17,
    }
    assert values("ఆరు వేలా ఐదు వందల రూపాయలు") == {"amount_rupees": 6500}
    assert values("₹6,500 పద్దెనిమిదో తేదీన ఇచ్చేస్తాను.") == {"amount_rupees": 6500, "day_of_month": 18}
    assert values("తొమ్మిది ఎనిమిది నాలుగు డబుల్ ఏడు ఒకటి రెండు జీరో జీరో జీరో") == {"phone": "9847712000"}


def test_ordinary_words_are_not_numbers():
    assert values("ఆరు నెలలు అయింది") == {}
    assert values("ఒక call చేయండి") == {}
    assert values("అర గంటలో వస్తాను") == {}
    assert values("పావు కిలో") == {}


def test_oblique_before_a_noun():
    assert telugu_cardinal(2500) == "రెండు వేల ఐదు వందలు"
    assert telugu_cardinal(2500, oblique=True) == "రెండు వేల ఐదు వందల"
    assert telugu_cardinal(150) == "నూట యాభై"
    assert telugu_cardinal(100_000, oblique=True) == "లక్ష"


def test_telugu_confusables():
    assert 60_000 in confusables.amount(20_000, "te")  # ఇరవై / అరవై
    assert 17_000 in confusables.amount(15_000, "te")  # పదిహేను / పదిహేడు
    assert 80_000 in confusables.amount(8_000, "te") or 80 * 1000 in confusables.amount(8000, "te")
    assert confusables.amount(20_000) == confusables.amount(20_000, "hi")


def test_hindi_cache_keys_did_not_move(monkeypatch):
    """Each key is the hash of a recogniser's settings. If one moves, the committed Hindi evidence is orphaned."""
    monkeypatch.delenv("PAKKA_LANG", raising=False)
    got = {
        "gpt-transcribe": params_sha(gpt_transcribe.plain().params),
        "gpt-transcribe+hints": params_sha(gpt_transcribe.hinted().params),
        "gpt-4o-transcribe": params_sha(gpt4o_transcribe.source().params),
        "saaras": params_sha({**saaras.source().params, "model": "saaras:v3"}),
        "verbx-vocaline": params_sha(verbx.source().params),
        "gpt-realtime-2.1": params_sha(realtime_agent.params()),
    }
    assert realtime_agent.params() == realtime_agent.PARAMS
    assert got == HINDI_KEYS


def test_telugu_settings_are_separate(monkeypatch):
    monkeypatch.setenv("PAKKA_LANG", "te")
    assert gpt_transcribe.plain().params["languages"] == ["te", "en"]
    assert saaras.source().params["language_code"] == "te-IN"
    assert "Telugu" in realtime_agent.params()["instructions"]
    assert params_sha(realtime_agent.params()) != HINDI_KEYS["gpt-realtime-2.1"]


def test_digit_grammar_uses_the_language():
    vocab = ["<unk>", *sorted({"▁" + w for ws in lang.TE.digit_words for w in ws}), "▁డబుల్", "<blk>"]
    pieces = Pieces(vocab, lang.TE)
    edges, end = phone_edges("99", lang=lang.TE)
    assert {e[2] for e in edges} == {"తొమ్మిది", "నైన్", "డబుల్ తొమ్మిది", "డబుల్ నైన్"}
    arcs, n_nodes, final = pieces.compile(edges, end)
    assert build_graph(arcs, n_nodes, pieces.blank, final_node=final).emit.size > 0


# Read from data/cache.sqlite, the committed responses behind the Hindi tables.
HINDI_KEYS = {
    "gpt-4o-transcribe": "dd63b1e5d73b0ae7",
    "gpt-realtime-2.1": "b4f68ff3ef4c3dae",
    "gpt-transcribe": "73eb5875f8e452f1",
    "gpt-transcribe+hints": "b7f7d03791cb17ac",
    "saaras": "9a0fd44fb0ed959e",
    "verbx-vocaline": "85fcdbcf65213f16",
}


def test_sandhi_and_recogniser_spellings():
    assert parse_number("లక్ష డెబ్బయైదు వేలు") == 175_000
    assert parse_number("ఇరవయ్యైదు వేలు") == 25_000
    assert parse_number("ముప్పయ్యారు వేలు") == 36_000
    assert parse_number("ఎనిమిది నర లక్షలు") == 850_000
    assert values("ముప్పయొక్కటో తేదీన అందుతుంది") == {"day_of_month": 31}
    assert values("డబో సిక్స్ త్రీ సెవెన్ డబో వన్ ఫోర్ డబో వన్ సిక్స్") == {"phone": "6637114116"}


def test_a_plural_scale_needs_its_multiplier():
    """A recogniser that garbles the multiplier must leave no amount, not one thousand."""
    assert values("ఏనీమడిన్నర వేల రూపాయలు సీఓడీ") == {}
    assert values("తొమ్మిది కన్నా లక్షల రూపాయల గురించి") == {}
    assert values("వేల రూపాయలు ఖర్చు అయింది") == {}
    assert values("వెయ్యి రూపాయలు") == {"amount_rupees": 1000}
    assert values("सौ रुपये") == {"amount_rupees": 100}


_WORDS = [
    *TE_0_99[:20], "ఇరవై", "అరవై", "వంద", "వందల", "వేల", "వేలు", "వెయ్యి", "లక్ష", "లక్షల", "అర", "పావు", "ముప్పావు",
    "నర", "రెండున్నర", "లక్షన్నర", "రెండొందలు", "డబుల్", "ట్రిపుల్", "ఒక", "రూపాయలు", "తేదీన", "జీరో", "ఫైవ్",
    "ట్వంటీ", "సోమవారం", "కి", "7", "98", "2.5", "17వ", "₹", "paune", "सौ", "hazaar", "double", "రెండువేల",
]  # fmt: skip


@given(st.lists(st.sampled_from(_WORDS), min_size=1, max_size=12))
@settings(max_examples=1500)
def test_no_word_order_crashes_the_parser(words):
    values(" ".join(words))
