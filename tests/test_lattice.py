from hypothesis import given
from hypothesis import strategies as st

from pramaan.lattice import (
    align,
    build,
    build_network,
    costs_from_confusion,
    differing_positions,
    medoid,
)
from pramaan.types import Evidence, Hypothesis

phones = st.from_regex(r"[6-9][0-9]{9}", fullmatch=True)


def hyp(source, family, **values):
    return Hypothesis(source=source, family=family, text="", latency_ms=0.0, values=values)


def ev(proposed, *hyps):
    return Evidence(audio_sha="x", proposed=proposed, hypotheses=hyps)


def test_align_handles_insert_and_delete():
    cost, pairs = align("9876543210", "987654321")
    assert cost == 1.0
    assert [a for a, _ in pairs] == list("9876543210")
    assert sum(1 for _, b in pairs if b == "") == 1
    cost, pairs = align("9876543210", "98765432100")
    assert cost == 1.0 and len(pairs) == 11


def test_confusion_costs_make_common_pairs_cheap():
    counts = [[100 if i == j else 0 for j in range(10)] for i in range(10)]
    counts[7][1] = counts[1][7] = 30
    costs = costs_from_confusion(counts)
    assert costs[7][1] < costs[7][2] == 1.0
    # With 7~1 cheap, the substitution beats two indels in a tie situation.
    assert align("17", "71", costs)[0] < align("17", "71")[0]


def test_medoid_prefers_majority():
    assert medoid([("9876543210", 1.0), ("9876543210", 1.0), ("9876543710", 1.0)]) == "9876543210"


@given(phones, st.integers(1, 5))
def test_lattice_of_identical_strings_returns_that_string(p, n):
    families = ["openai-transcribe", "elevenlabs", "sarvam", "ai4bharat", "openai-transcribe"]
    lat = build(ev({"phone": p}, *[hyp(f"s{i}", families[i], phone=p) for i in range(n)]), "phone")
    assert lat.candidates[0] == p
    assert lat.network is not None and lat.network.medoid == p
    assert lat.contested_positions == ()
    assert all(lat.network.distribution(i) == {p[i]: 1.0} for i in range(10))


def test_phone_network_votes_and_contested_digit():
    lat = build(
        ev(
            {"phone": "9876543210"},
            hyp("gt", "openai-transcribe", phone="9876543210"),
            hyp("scribe", "elevenlabs", phone="9876543710"),
            hyp("saaras", "sarvam", phone="9876543210"),
        ),
        "phone",
    )
    assert lat.contested_positions == (7,)
    assert lat.network is not None
    dist = lat.network.distribution(7)
    assert dist["2"] > dist["7"] > 0
    assert set(lat.candidates[:2]) == {"9876543210", "9876543710"}
    assert lat.supporting_families("9876543210") == ("openai-transcribe", "sarvam")


def test_nine_and_eleven_digit_readings_align():
    lat = build(
        ev(
            {"phone": "9876543210"},
            hyp("a", "openai-transcribe", phone="9876543210"),
            hyp("b", "elevenlabs", phone="987654321"),
            hyp("c", "sarvam", phone="98765432100"),
            hyp("d", "ai4bharat", phone="9876543210"),
        ),
        "phone",
    )
    assert lat.network is not None and lat.network.medoid == "9876543210"
    assert lat.candidates[0] == "9876543210"
    # Malformed readings vote in the network but are never offered as candidates.
    assert all(len(str(c)) == 10 for c in lat.candidates)


def test_network_recombines_digits_into_extra_candidates():
    lat = build(
        ev(
            {"phone": "9876543210"},
            hyp("a", "openai-transcribe", phone="9876543210"),
            hyp("b", "elevenlabs", phone="9176543210"),
            hyp("c", "sarvam", phone="9876543710"),
        ),
        "phone",
    )
    assert "9176543710" in lat.candidates
    assert lat.support_weight("9176543710") == 0.0
    assert lat.contested_positions == (1, 7)


def test_agent_family_never_supports_and_variants_count_once():
    lat = build(
        ev(
            {"amount_rupees": 2750},
            hyp("rt", "openai-realtime", amount_rupees=2750),
            hyp("gt", "openai-transcribe", amount_rupees=2750),
            hyp("gt+h", "openai-transcribe", amount_rupees=2750),
            hyp("scribe", "elevenlabs", amount_rupees=3750),
        ),
        "amount_rupees",
    )
    assert lat.support["2750"] == {"openai-transcribe": 1.0}
    assert "rt" in lat.sources["2750"]
    assert lat.families_present == ("elevenlabs", "openai-transcribe")
    assert lat.unstable_families == ()


def test_unstable_family_splits_its_vote():
    lat = build(
        ev(
            {"amount_rupees": 2750},
            hyp("gt", "openai-transcribe", amount_rupees=2750),
            hyp("gt+h", "openai-transcribe", amount_rupees=3750),
        ),
        "amount_rupees",
    )
    assert lat.unstable_families == ("openai-transcribe",)
    assert lat.support_weight(2750) == 0.5
    assert lat.supporting_families(2750) == ()


def test_amounts_never_fabricated_and_contested_places():
    lat = build(
        ev(
            {"amount_rupees": 2750},
            hyp("a", "openai-transcribe", amount_rupees=2750),
            hyp("b", "elevenlabs", amount_rupees=2150),
        ),
        "amount_rupees",
    )
    assert set(lat.candidates) == {2750, 2150}
    assert lat.contested_positions == (1,)


def test_proposed_kept_under_cap():
    hyps = [hyp(f"s{i}", "elevenlabs", amount_rupees=1000 + i) for i in range(10)]
    lat = build(ev({"amount_rupees": 99}, *hyps), "amount_rupees", max_candidates=3)
    assert len(lat.candidates) == 3 and 99 in lat.candidates


def test_differing_positions():
    assert differing_positions(["123", "133"]) == (1,)
    assert differing_positions(["123", "1234"]) == ()


@given(st.permutations(range(4)))
def test_build_invariant_to_hypothesis_order(order):
    hs = [
        hyp("a", "openai-transcribe", phone="9876543210"),
        hyp("b", "elevenlabs", phone="9876543710"),
        hyp("c", "sarvam", phone="987654321"),
        hyp("d", "openai-transcribe", phone="9876543211"),
    ]
    base = build(ev({"phone": "9876543210"}, *hs), "phone")
    assert build(ev({"phone": "9876543210"}, *[hs[i] for i in order]), "phone") == base


def test_empty_network():
    assert build_network([]) is None
