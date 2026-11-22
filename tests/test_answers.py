import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pramaan import normalise, question
from pramaan.confusables import neighbours
from pramaan.decide import decide, resolve_answer
from pramaan.lattice import canon, is_valid
from pramaan.render import renderings
from pramaan.types import Asked, Evidence, Hypothesis, Policy, Verdict

POLICY = Policy(require_witness=False, accept_threshold=0.0)


def hyp(family: str, text: str) -> Hypothesis:
    return Hypothesis(source=family, family=family, text=text, latency_ms=1.0, values=normalise.values(text))


def evidence(slot: str, proposed: object, *heard: tuple[str, str]) -> Evidence:
    return Evidence(audio_sha="x", proposed={slot: proposed}, hypotheses=tuple(hyp(f, t) for f, t in heard))


@pytest.mark.parametrize(
    ("text", "slot", "value"),
    [
        ("मेरा पिन कोड है पाँच शून्य शून्य शून्य तीन दो", "pincode", "500032"),
        ("my pin code is 500032", "pincode", "500032"),
        ("मेरा खाता नंबर है एक नौ शून्य चार एक छह तीन एक पाँच पाँच छह", "account_number", "19041631556"),
        ("account number is zero one two three four five six seven eight", "account_number", "012345678"),
    ],
)
def test_labelled_digit_runs(text, slot, value):
    assert normalise.values(text)[slot] == value


def test_unlabelled_runs_keep_their_old_meaning():
    assert normalise.values("नौ आठ सात छह पाँच चार तीन दो एक शून्य") == {"phone": "9876543210"}
    assert "pincode" not in normalise.values("पाँच लाख रुपये")


@pytest.mark.parametrize(
    ("slot", "value", "ok"),
    [
        ("pincode", "500032", True),
        ("pincode", "050032", False),
        ("pincode", "50003", False),
        ("account_number", "012345678", True),
        ("account_number", "12345678", False),
    ],
)
def test_validity(slot, value, ok):
    assert is_valid(slot, value) is ok


@pytest.mark.parametrize(
    ("slot", "options", "text", "chosen"),
    [
        ("phone", ("9755507388", "9655507388"), "छह", "9655507388"),
        ("phone", ("9755507388", "9655507388"), "जी, दूसरा वाला", "9655507388"),
        ("pincode", ("541963", "541962"), "teen", "541963"),
        ("day_of_month", (21, 14), "चौदह", 14),
        ("amount_rupees", (3000, 2000), "तीन", 3000),
        ("phone", ("9755507388", "9655507388"), "सात नहीं छह", None),
        ("phone", ("9755507388", "9655507388"), "हाँ", None),
        ("phone", ("9755507388", "9655507388"), "one second", None),
    ],
)
def test_pick(slot, options, text, chosen):
    assert question.pick(slot, options, text, normalise.values(text).get(slot)) == chosen


def test_short_answer_from_two_families_overrides_the_held_value():
    asked = Asked(slot="phone", options=("9755507388", "9655507388"))
    ev = evidence("phone", "9755507388", ("sarvam", "छह"), ("verbx", "six"))
    d = decide(resolve_answer(ev, POLICY, asked), POLICY)
    assert d.verdict == Verdict.PASS and d.execute == {"phone": "9655507388"}


@pytest.mark.parametrize(
    "heard",
    [
        (("sarvam", "छह"),),
        (("sarvam", "छह"), ("verbx", "seven")),
        (("sarvam", "छह"), ("verbx", "नौ आठ सात छह पाँच चार तीन दो एक शून्य")),
    ],
)
def test_short_answer_needs_independent_agreement(heard):
    asked = Asked(slot="phone", options=("9755507388", "9655507388"))
    ev = evidence("phone", "9755507388", *heard)
    assert resolve_answer(ev, POLICY, asked) == ev


def test_label_followed_by_a_devanagari_is():
    assert normalise.values("माय अकाउंट नंबर इज 85192403607")["account_number"] == "85192403607"


PIN = st.from_regex(r"[1-9][0-9]{5}", fullmatch=True)
ACCOUNT = st.from_regex(r"[0-9]{9,18}", fullmatch=True)
LABELS = {
    ("pincode", "hi"): "मेरा पिन कोड है {}",
    ("pincode", "en"): "my pin code is {}",
    ("pincode", "te"): "నా పిన్ కోడ్ {}",
    ("account_number", "hi"): "मेरा खाता नंबर है {}",
    ("account_number", "en"): "my account number is {}",
    ("account_number", "te"): "నా అకౌంట్ నంబర్ {}",
}


@settings(max_examples=150)
@given(data=st.data(), key=st.sampled_from(sorted(LABELS)))
def test_every_spoken_rendering_of_a_pin_or_account_number_parses_back(data, key):
    slot, lang = key
    value = data.draw(PIN if slot == "pincode" else ACCOUNT)
    forms = renderings(slot, value, "te" if lang == "te" else "hi")
    assert forms
    for form in forms:
        assert normalise.values(LABELS[key].format(form)).get(slot) == value, form
    assert normalise.values(LABELS[key].format(value)).get(slot) == value


@settings(max_examples=150)
@given(data=st.data(), slot=st.sampled_from(["pincode", "account_number"]))
def test_confusable_neighbours_of_a_pin_or_account_number_are_digit_strings(data, slot):
    value = data.draw(PIN if slot == "pincode" else ACCOUNT)
    near = neighbours(slot, value)
    assert near and value not in near
    assert all(n.isascii() and n.isdigit() and abs(len(n) - len(value)) <= 1 for n in near)


@pytest.mark.parametrize(("slot", "said", "misheard"), [("pincode", "500032", "500072"), ("account_number", "19041631556", "19041631596")])  # fmt: skip
def test_a_misheard_pin_or_account_digit_is_repaired_or_asked_never_passed(slot, said, misheard):
    label = "pin code" if slot == "pincode" else "account number"
    agreed = evidence(slot, misheard, ("sarvam", f"my {label} is {said}"), ("verbx", f"my {label} is {said}"))
    d = decide(agreed, POLICY)
    assert d.verdict == Verdict.PASS and d.execute == {slot: said}
    split = evidence(
        slot, misheard, ("sarvam", f"my {label} is {said}"), ("verbx", f"my {label} is {misheard}")
    )
    assert decide(split, POLICY).verdict == Verdict.ASK
    alone = evidence(slot, misheard, ("sarvam", f"my {label} is {misheard}"))
    assert decide(alone, POLICY).verdict != Verdict.PASS


@pytest.mark.parametrize("value", ["५६००३४", "50003²"])
def test_non_ascii_digits_are_not_a_value(value):
    assert canon("pincode", value) is None
    assert neighbours("pincode", value) == []
