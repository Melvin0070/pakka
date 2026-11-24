import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pakka.decide import decide
from pakka.lattice import build
from pakka.question import option_order, phrase, roman_cardinal
from pakka.score import FEATURES, features, fixed_rule, score
from pakka.types import Evidence, Hypothesis, Policy, SlotDecision, Verdict, WitnessScore

POLICY = Policy()


def hyp(source, family, lp=None, **values):
    return Hypothesis(
        source=source,
        family=family,
        text="",
        latency_ms=0.0,
        values=values,
        value_min_logprob={k: lp for k in values} if lp is not None else {},
    )


def wit(slot, **ll):
    return WitnessScore(slot=slot, loglik={k.lstrip("v"): v for k, v in ll.items()})


def ev(proposed, hyps, witness=()):
    return Evidence(audio_sha="x", proposed=proposed, hypotheses=tuple(hyps), witness=tuple(witness))


AGREE = [
    hyp("rt", "openai-realtime", amount_rupees=2750),
    hyp("gt", "openai-transcribe", amount_rupees=2750),
    hyp("scribe", "elevenlabs", amount_rupees=2750),
    hyp("saaras", "sarvam", amount_rupees=2750),
]


def test_pass_when_families_and_witness_agree():
    d = decide(ev({"amount_rupees": 2750}, AGREE, [wit("amount_rupees", v2750=-2.0, v3750=-6.0)]), POLICY)
    assert d.verdict == Verdict.PASS
    sd = d.slots[0]
    assert sd.reason == "families_agree"
    assert sd.supporting_families == ("elevenlabs", "openai-transcribe", "sarvam")
    assert sd.witness_llr == 4.0
    assert d.question is None and d.policy_hash == POLICY.hash


def test_witness_required():
    d = decide(ev({"amount_rupees": 2750}, AGREE), POLICY)
    assert d.verdict == Verdict.BLOCK and d.slots[0].reason == "witness_absent"
    d = decide(ev({"amount_rupees": 2750}, AGREE), Policy(require_witness=False))
    assert d.verdict == Verdict.PASS


def test_agent_alone_is_not_support():
    hs = [
        hyp("rt", "openai-realtime", amount_rupees=2750),
        hyp("gt", "openai-transcribe", amount_rupees=2750),
    ]
    d = decide(ev({"amount_rupees": 2750}, hs, [wit("amount_rupees", v2750=-1.0)]), POLICY)
    assert d.verdict == Verdict.BLOCK and d.slots[0].reason == "insufficient_families"


def test_ask_when_split_between_two_amounts():
    hs = [
        hyp("gt", "openai-transcribe", amount_rupees=2750),
        hyp("scribe", "elevenlabs", amount_rupees=3500),
        hyp("saaras", "sarvam", amount_rupees=2750),
    ]
    d = decide(ev({"amount_rupees": 2750}, hs, [wit("amount_rupees", v2750=-5.0, v3500=-3.0)]), POLICY)
    assert d.verdict == Verdict.ASK
    sd = d.slots[0]
    assert sd.reason == "witness_prefers_other"
    assert set(sd.candidates) == {2750, 3500}
    assert d.question_slot == "amount_rupees"
    assert d.question in (
        "Do hazaar saat sau pachaas, ya teen hazaar paanch sau?",
        "Teen hazaar paanch sau, ya do hazaar saat sau pachaas?",
    )


def test_phone_contested_digit_question():
    hs = [
        hyp("gt", "openai-transcribe", phone="9876543210"),
        hyp("scribe", "elevenlabs", phone="9876543710"),
        hyp("saaras", "sarvam", phone="9876543210"),
    ]
    d = decide(ev({"phone": "9876543210"}, hs, [wit("phone", v9876543210=-4.0, v9876543710=-3.0)]), POLICY)
    assert d.verdict == Verdict.ASK
    assert d.slots[0].contested_positions == (7,)
    assert d.question in ("Aakhri se teesra ank do hai ya saat?", "Aakhri se teesra ank saat hai ya do?")


def test_invented_and_no_evidence_and_malformed():
    hs = [hyp("gt", "openai-transcribe", amount_rupees=500), hyp("scribe", "elevenlabs")]
    d = decide(ev({"day_of_month": 5}, hs), POLICY)
    assert d.verdict == Verdict.BLOCK and d.slots[0].reason == "invented"
    d = decide(ev({"day_of_month": 5}, [hyp("rt", "openai-realtime", day_of_month=5)]), POLICY)
    assert d.slots[0].reason == "no_evidence"
    d = decide(ev({"phone": "987654321"}, hs), POLICY)
    assert d.slots[0].reason == "malformed"
    assert d.question == "Maaf kijiye, number ek baar phir se dheere boliye?"


def test_mismatch_when_one_clear_alternative():
    hs = [
        hyp("rt", "openai-realtime", weekday="tuesday"),
        hyp("gt", "openai-transcribe", weekday="thursday"),
        hyp("scribe", "elevenlabs", weekday="thursday"),
    ]
    e = ev({"weekday": "tuesday"}, hs, [wit("weekday", tuesday=-5.0, thursday=-2.0)])
    d = decide(e, POLICY.model_copy(update={"repair": False}))
    assert d.verdict == Verdict.BLOCK and d.slots[0].reason == "mismatch"
    assert d.slots[0].candidates[0] == "thursday"


def test_repair_replaces_the_value_only_when_one_alternative_passes():
    hs = [hyp("gt", "openai-transcribe", weekday="thursday"), hyp("scribe", "elevenlabs", weekday="thursday")]
    d = decide(ev({"weekday": "tuesday"}, hs, [wit("weekday", tuesday=-5.0, thursday=-2.0)]), POLICY)
    assert d.verdict == Verdict.PASS and d.slots[0].reason == "repaired"
    assert d.slots[0].proposed == "tuesday" and d.execute == {"weekday": "thursday"}
    # The witness prefers the agent's value over the transcribers': nothing passes, so nothing is repaired.
    d = decide(ev({"weekday": "tuesday"}, hs, [wit("weekday", tuesday=-2.0, thursday=-9.0)]), POLICY)
    assert d.verdict != Verdict.PASS and d.execute == {}


def test_no_repair_when_a_family_heard_the_agents_value():
    hs = [
        hyp("gt", "openai-transcribe", day_of_month=30),
        hyp("vx", "verbx", day_of_month=3),
        hyp("ic", "ai4bharat", day_of_month=3),
    ]
    d = decide(ev({"day_of_month": 30}, hs, [wit("day_of_month", **{"30": -9.0, "3": -2.0})]), POLICY)
    assert d.verdict == Verdict.ASK and d.execute == {}
    assert set(d.slots[0].candidates) == {30, 3}


def test_no_repair_when_a_family_heard_a_third_value():
    hs = [
        hyp("gt", "openai-transcribe", amount_rupees=900),
        hyp("vx", "verbx", amount_rupees=900),
        hyp("ic", "ai4bharat", amount_rupees=900),
        hyp("sv", "sarvam", amount_rupees=875),
    ]
    w = [wit("amount_rupees", **{"950": -30.0, "900": -2.0, "875": -20.0})]
    d = decide(ev({"amount_rupees": 950}, hs, w), POLICY)
    assert d.verdict != Verdict.PASS and d.execute == {}
    d = decide(ev({"amount_rupees": 950}, hs[:3], w), POLICY)
    assert d.slots[0].reason == "repaired" and d.execute == {"amount_rupees": 900}


def test_omitted_slot_is_filled_or_held():
    hs = [
        hyp("gt", "openai-transcribe", weekday="friday", amount_rupees=500),
        hyp("scribe", "elevenlabs", weekday="friday", amount_rupees=500),
    ]
    w = [wit("weekday", friday=-1.0, monday=-9.0)]
    held = decide(ev({"weekday": "friday"}, hs, w), POLICY)
    assert held.verdict == Verdict.BLOCK and held.slots[-1].reason == "omitted"
    lax = POLICY.model_copy(update={"require_witness": False})
    filled = decide(ev({"weekday": "friday"}, hs, w), lax)
    assert filled.verdict == Verdict.PASS and filled.execute == {"weekday": "friday", "amount_rupees": 500}


def test_too_many_candidates_blocks():
    hs = [
        hyp(f"s{i}", f, amount_rupees=1000 * (i + 1))
        for i, f in enumerate(["openai-transcribe", "elevenlabs", "sarvam", "ai4bharat"])
    ]
    d = decide(
        ev({"amount_rupees": 1000}, hs, [wit("amount_rupees", v1000=-1, v2000=-1, v3000=-1, v4000=-1)]),
        POLICY,
    )
    assert d.slots[0].verdict == Verdict.BLOCK and d.slots[0].reason == "too_many_candidates"


def test_omitted_slot_is_not_guarded():
    hs = AGREE + [hyp("x", "elevenlabs", phone="9876543210")]
    d = decide(ev({"amount_rupees": 2750}, hs, [wit("amount_rupees", v2750=-1.0)]), POLICY)
    assert [s.slot for s in d.slots] == ["amount_rupees"]


def test_verdict_is_worst_and_score_is_min():
    hs = AGREE + [hyp("gt", "openai-transcribe", day_of_month=5)]
    d = decide(ev({"amount_rupees": 2750, "day_of_month": 5}, hs, [wit("amount_rupees", v2750=-1.0)]), POLICY)
    assert d.verdict == Verdict.BLOCK
    assert d.score == min(s.score for s in d.slots)
    assert d.question_slot == "day_of_month"


def test_empty_proposal_passes():
    d = decide(ev({}, AGREE), POLICY)
    assert d.verdict == Verdict.PASS and d.slots == ()


def test_logistic_weights_and_unknown_feature():
    f = features(
        ev({"amount_rupees": 2750}, AGREE),
        build(ev({"amount_rupees": 2750}, AGREE), "amount_rupees"),
        "amount_rupees",
    )
    assert set(f) == set(FEATURES)
    assert score(f, Policy(weights={"support_frac": 4.0}, bias=-2.0)) == pytest.approx(0.8807970779)
    with pytest.raises(KeyError):
        score(f, Policy(weights={"nope": 1.0}))


def test_roman_numbers_and_option_order():
    assert roman_cardinal(2750) == "do hazaar saat sau pachaas"
    assert roman_cardinal(250000) == "do lakh pachaas hazaar"
    assert option_order([1, 2, 3]) == option_order([3, 1, 2])
    sd = SlotDecision(
        slot="weekday",
        proposed="tuesday",
        verdict=Verdict.ASK,
        reason="x",
        candidates=("tuesday", "thursday"),
    )
    assert phrase(sd) in ("Mangalvaar, ya guruvaar?", "Guruvaar, ya mangalvaar?")


# ---------------------------------------------------------------- properties

FAMS = ["openai-realtime", "openai-transcribe", "elevenlabs", "sarvam", "ai4bharat"]
amounts = st.sampled_from([2750, 3750, 2150, 1500])
hyp_st = st.builds(
    lambda i, fam, a, lp: hyp(f"src{i}", fam, lp, amount_rupees=a),
    st.integers(0, 3),
    st.sampled_from(FAMS),
    amounts,
    st.one_of(st.none(), st.floats(-8, 0)),
)
witness_st = st.one_of(
    st.just(()),
    st.dictionaries(st.sampled_from(["2750", "3750", "2150", "1500"]), st.floats(-20, 0), min_size=1).map(
        lambda d: (WitnessScore(slot="amount_rupees", loglik=d),)
    ),
)


@settings(max_examples=150, deadline=None)
@given(st.lists(hyp_st, max_size=7), witness_st, amounts, st.randoms(use_true_random=False))
def test_decide_deterministic_and_order_invariant(hs, w, proposed, rnd):
    e = ev({"amount_rupees": proposed}, hs, w)
    shuffled = list(hs)
    rnd.shuffle(shuffled)
    d = decide(e, POLICY)
    assert decide(e, POLICY) == d
    assert decide(ev({"amount_rupees": proposed}, shuffled, w), POLICY) == d
    assert 0.0 <= d.score <= 1.0


@settings(max_examples=150, deadline=None)
@given(st.lists(hyp_st, max_size=6), witness_st, amounts, st.sampled_from(FAMS[1:]))
def test_adding_supporting_family_never_lowers_score(hs, w, proposed, new_family):
    present = {h.family for h in hs}
    if new_family in present:
        return
    before = ev({"amount_rupees": proposed}, hs, w)
    after = ev({"amount_rupees": proposed}, [*hs, hyp("new", new_family, amount_rupees=proposed)], w)

    def s(e):
        lat = build(e, "amount_rupees")
        return fixed_rule(features(e, lat, "amount_rupees"))

    assert s(after) >= s(before) - 1e-12


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.sampled_from(["9876543210", "9876543710", "9176543210", "987654321"]), min_size=1, max_size=4
    ),
    st.randoms(use_true_random=False),
)
def test_phone_decision_order_invariant(phones, rnd):
    hs = [hyp(f"s{i}", FAMS[1 + i % 4], phone=p) for i, p in enumerate(phones)]
    e = ev({"phone": "9876543210"}, hs, [wit("phone", v9876543210=-3.0, v9876543710=-3.5)])
    shuffled = list(hs)
    rnd.shuffle(shuffled)
    assert decide(ev({"phone": "9876543210"}, shuffled, e.witness), POLICY) == decide(e, POLICY)
