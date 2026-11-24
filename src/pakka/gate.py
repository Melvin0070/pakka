"""Threshold choice and risk bounds, with no statistics library.

- binom_cdf: exact lower tail, summed in log space.
- cp_upper: one-sided Clopper-Pearson upper bound, by bisection on binom_cdf.
- ltt_select: Learn-then-Test fixed-sequence testing over thresholds, strict to permissive.
- risk_coverage, speaker_bound, n_eff (design effect), eprocess (betting e-process).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


def _log_pmf(i: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if i == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if i == n else -math.inf
    return (
        math.lgamma(n + 1)
        - math.lgamma(i + 1)
        - math.lgamma(n - i + 1)
        + i * math.log(p)
        + (n - i) * math.log1p(-p)
    )


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    logs = [_log_pmf(i, n, p) for i in range(k + 1)]
    top = max(logs)
    if top == -math.inf:
        return 0.0
    return min(1.0, math.exp(top) * sum(math.exp(v - top) for v in logs))


def cp_upper(k: int, n: int, delta: float = 0.05) -> float:
    """Smallest p with P(X <= k | n, p) <= delta: the 1 - delta one-sided upper bound on the error rate."""
    if n <= 0 or k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if binom_cdf(k, n, mid) > delta:
            lo = mid
        else:
            hi = mid
    return hi


def min_n_certifiable(alpha: float, delta: float) -> int:
    """Fewest accepted actions for which zero errors certifies risk <= alpha."""
    return math.ceil(math.log(delta) / math.log1p(-alpha))


@dataclass(frozen=True)
class LTTRow:
    threshold: float
    n: int  # accepted at this threshold
    k: int  # wrong among accepted
    p_value: float | None  # None: skipped as untestable
    rejected: bool


@dataclass(frozen=True)
class LTTResult:
    threshold: float | None  # most permissive certified threshold; None if none
    alpha: float
    delta: float
    table: tuple[LTTRow, ...]


def _counts(pairs: Sequence[tuple[float, bool]], t: float) -> tuple[int, int]:
    acc = [wrong for s, wrong in pairs if s >= t]
    return len(acc), sum(acc)


def ltt_select(
    pairs: Iterable[tuple[float, bool]],
    alpha: float = 0.05,
    delta: float = 0.05,
    grid: Sequence[float] | None = None,
    skip_untestable: bool = True,
) -> LTTResult:
    """pairs: (score, is_wrong). H_j: risk among accepted at threshold j exceeds alpha; p_j = BinomCDF(k_j; n_j, alpha).

    Thresholds are tested strict to permissive and testing stops at the first non-rejection. With
    skip_untestable, thresholds accepting fewer than min_n_certifiable actions are passed over without
    stopping: that choice depends on the scores alone, never the labels, so the order stays fixed given
    the scores. Without it, a strict end with a handful of accepts ends the sequence at once.
    """
    data = [(float(s), bool(w)) for s, w in pairs]
    ts = sorted(set(grid if grid is not None else (s for s, _ in data)), reverse=True)
    n_min = min_n_certifiable(alpha, delta)
    rows: list[LTTRow] = []
    best: float | None = None
    stopped = False
    for t in ts:
        n, k = _counts(data, t)
        if stopped:
            rows.append(LTTRow(t, n, k, None, False))
            continue
        if skip_untestable and n < n_min:
            rows.append(LTTRow(t, n, k, None, False))
            continue
        p = binom_cdf(k, n, alpha)
        ok = p <= delta
        rows.append(LTTRow(t, n, k, p, ok))
        if ok:
            best = t
        else:
            stopped = True
    return LTTResult(threshold=best, alpha=alpha, delta=delta, table=tuple(rows))


@dataclass(frozen=True)
class RiskPoint:
    threshold: float
    coverage: float
    risk: float
    n: int
    k: int
    upper: float


def risk_coverage(pairs: Iterable[tuple[float, bool]], delta: float = 0.05) -> list[RiskPoint]:
    data = [(float(s), bool(w)) for s, w in pairs]
    total = len(data)
    out: list[RiskPoint] = []
    for t in sorted({s for s, _ in data}, reverse=True):
        n, k = _counts(data, t)
        out.append(
            RiskPoint(t, n / total if total else 0.0, k / n if n else 0.0, n, k, cp_upper(k, n, delta))
        )
    return out


@dataclass(frozen=True)
class SpeakerBound:
    speakers: int  # speakers with at least one accepted action
    speakers_with_error: int
    upper: float


def speaker_bound(
    accepted_wrong_by_speaker: Mapping[str, Sequence[bool]], delta: float = 0.05
) -> SpeakerBound:
    """Speakers as the unit: bound on the fraction of speakers who suffer any silent wrong action.

    Valid under clustering because speakers, not actions, are the independent draws.
    """
    groups = [list(v) for v in accepted_wrong_by_speaker.values() if len(v) > 0]
    n = len(groups)
    k = sum(1 for g in groups if any(g))
    return SpeakerBound(n, k, cp_upper(k, n, delta))


def design_effect(mean_cluster_size: float, icc: float) -> float:
    return 1.0 + (mean_cluster_size - 1.0) * icc


def n_eff(n: int, n_clusters: int, icc: float) -> float:
    """Effective sample size of n actions spread over n_clusters speakers with intra-class correlation icc."""
    if n_clusters <= 0:
        return 0.0
    return n / design_effect(n / n_clusters, icc)


@dataclass(frozen=True)
class EProcessResult:
    wealth: tuple[float, ...]
    certified_at: int | None  # 1-based count of observations when wealth first reached 1/delta


def eprocess(
    errors: Iterable[bool | int], alpha: float = 0.05, delta: float = 0.05, bet: float = 0.5
) -> EProcessResult:
    """W_t = prod(1 + bet * (alpha - X_i)), a nonnegative supermartingale when the true risk is >= alpha.

    Ville's inequality lets risk <= alpha be certified the first time W_t >= 1/delta, at any stopping time,
    so labelled calls can keep arriving. bet = 0.5 needs 122 clean accepts at alpha = delta = 0.05.
    """
    if not 0.0 <= bet < 1.0 / (1.0 - alpha):
        raise ValueError("bet must keep every factor positive")
    w = 1.0
    path: list[float] = []
    hit: int | None = None
    for t, x in enumerate(errors, start=1):
        w *= 1.0 + bet * (alpha - float(x))
        path.append(w)
        if hit is None and w >= 1.0 / delta:
            hit = t
    return EProcessResult(tuple(path), hit)
