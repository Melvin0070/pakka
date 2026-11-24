import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pakka.gate import (
    binom_cdf,
    cp_upper,
    eprocess,
    ltt_select,
    min_n_certifiable,
    n_eff,
    risk_coverage,
    speaker_bound,
)


def test_binom_cdf_exact():
    assert binom_cdf(0, 10, 0.5) == pytest.approx(1 / 1024)
    assert binom_cdf(5, 10, 0.5) == pytest.approx(sum(math.comb(10, i) for i in range(6)) / 1024)
    assert binom_cdf(10, 10, 0.3) == 1.0 and binom_cdf(-1, 10, 0.3) == 0.0


@pytest.mark.parametrize(
    ("k", "n", "bound"),
    [(0, 59, 0.0495), (0, 60, 0.0487), (2, 150, 0.0414), (8, 300, 0.0476), (0, 299, 0.0100)],
)
def test_clopper_pearson_reference_values(k, n, bound):
    assert cp_upper(k, n) == pytest.approx(bound, abs=5e-5)


def test_certifiability_thresholds():
    assert cp_upper(0, 59) <= 0.05 < cp_upper(0, 58)
    assert min_n_certifiable(0.05, 0.05) == 59


@given(st.integers(1, 400), st.data())
def test_bound_monotone_in_k(n, data):
    k = data.draw(st.integers(0, n - 1))
    assert cp_upper(k, n) <= cp_upper(k + 1, n)
    assert cp_upper(k, n) >= k / n


def _pairs(n_good, n_bad, good_score=0.9, bad_score=0.3):
    return [(good_score, False)] * n_good + [(bad_score, True)] * n_bad


def test_ltt_picks_most_permissive_certified_threshold():
    pairs = _pairs(100, 0) + [(0.6, False)] * 40 + [(0.5, True)] * 30
    res = ltt_select(pairs, alpha=0.05, delta=0.05)
    assert res.threshold == 0.6
    tested = [r for r in res.table if r.p_value is not None]
    assert [r.rejected for r in tested] == [True, True, False]
    assert res.table[-1].p_value is None or not res.table[-1].rejected


def test_ltt_none_when_too_few():
    assert ltt_select(_pairs(30, 0)).threshold is None
    strict = ltt_select(_pairs(30, 0) + _pairs(70, 0, good_score=0.8), skip_untestable=False)
    assert strict.threshold is None  # the 30-accept head cannot be rejected and ends the sequence


def test_risk_coverage_curve():
    curve = risk_coverage(_pairs(90, 10))
    assert curve[0].coverage == 0.9 and curve[0].risk == 0.0
    assert curve[-1].coverage == 1.0 and curve[-1].risk == pytest.approx(0.1)


def test_speaker_bound_and_design_effect():
    sb = speaker_bound({"a": [False, False], "b": [True, False], "c": [], "d": [False]})
    assert (sb.speakers, sb.speakers_with_error) == (3, 1)
    assert sb.upper == pytest.approx(cp_upper(1, 3))
    assert n_eff(300, 300, 0.2) == 300
    assert n_eff(300, 30, 0.1) == pytest.approx(300 / 1.9)


def test_eprocess():
    r = eprocess([0] * 200)
    assert r.certified_at == math.ceil(math.log(20) / math.log(1.025))
    assert eprocess([1, 0] * 100).certified_at is None
    with pytest.raises(ValueError):
        eprocess([0], bet=2.0)
