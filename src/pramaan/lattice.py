"""Candidate values for one slot, with who supports each, and a digit confusion network for phones.

Pure. Sources are grouped by family; the agent's own family never supports its own proposal.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .lexicon import WEEKDAYS
from .types import Evidence, Hypothesis, Slot, Value

AGENT_FAMILY = "openai-realtime"
EPS = ""  # epsilon token in the confusion network
# Additive smoothing for path probabilities; keeps unseen digits possible but far less likely than any vote.
NET_SMOOTHING = 0.1
NET_VOCAB = 11  # ten digits plus epsilon
_MAX_PATH_POPS = 512

SubCosts = Sequence[Sequence[float]]


# ---------------------------------------------------------------- typed values


def canon(slot: str, value: object) -> Value | None:
    """Coerce a typed value to its canonical form; None when it cannot be one."""
    if value is None or isinstance(value, bool):
        return None
    if slot in ("amount_rupees", "day_of_month"):
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return None
    if slot == "weekday":
        return value.strip().lower() if isinstance(value, str) and value.strip() else None
    if slot == "phone":
        s = str(value).strip()
        return s if s.isdigit() else None
    return None


def is_valid(slot: str, value: Value | None) -> bool:
    if value is None:
        return False
    if slot == "amount_rupees":
        return isinstance(value, int) and 0 < value < 1_000_000_000
    if slot == "day_of_month":
        return isinstance(value, int) and 1 <= value <= 31
    if slot == "weekday":
        return value in WEEKDAYS
    if slot == "phone":
        return isinstance(value, str) and len(value) == 10 and value[0] in "6789" and value.isdigit()
    return False


def key(value: Value) -> str:
    return str(value)


def differing_positions(values: Iterable[Value]) -> tuple[int, ...]:
    """Left-to-right character indexes where same-length renderings differ; () if lengths differ."""
    strs = [str(v) for v in values]
    if len(strs) < 2 or len({len(s) for s in strs}) != 1:
        return ()
    return tuple(i for i in range(len(strs[0])) if len({s[i] for s in strs}) > 1)


# ---------------------------------------------------------------- alignment


def uniform_costs() -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(0.0 if i == j else 1.0 for j in range(10)) for i in range(10))


def costs_from_confusion(counts: SubCosts, floor: float = 0.2) -> tuple[tuple[float, ...], ...]:
    """Substitution costs from a 10x10 count matrix (row = said, column = heard).

    Cost is 1 minus the symmetrised confusion rate scaled to the most confused pair, floored so that a
    frequent confusion is cheap but never free.
    """
    rate = [[0.0] * 10 for _ in range(10)]
    for i in range(10):
        row = sum(counts[i]) or 1.0
        for j in range(10):
            rate[i][j] = counts[i][j] / row
    sym = [[(rate[i][j] + rate[j][i]) / 2 if i != j else 0.0 for j in range(10)] for i in range(10)]
    top = max(max(r) for r in sym) or 1.0
    return tuple(
        tuple(0.0 if i == j else max(floor, 1.0 - sym[i][j] / top) for j in range(10)) for i in range(10)
    )


def _sub(costs: SubCosts, a: str, b: str) -> float:
    return 0.0 if a == b else float(costs[int(a)][int(b)])


def align(
    a: str, b: str, costs: SubCosts | None = None, indel: float = 1.0
) -> tuple[float, list[tuple[str, str]]]:
    """Weighted Levenshtein alignment of digit strings. Pairs are (a_char, b_char) with EPS for a gap."""
    c = costs or uniform_costs()
    n, m = len(a), len(b)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i * indel
    for j in range(1, m + 1):
        d[0][j] = j * indel
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(
                d[i - 1][j - 1] + _sub(c, a[i - 1], b[j - 1]), d[i - 1][j] + indel, d[i][j - 1] + indel
            )
    pairs: list[tuple[str, str]] = []
    i, j = n, m
    # Tie order (match/substitute, then delete, then insert) is fixed so alignments are reproducible.
    while i or j:
        if i and j and math.isclose(d[i][j], d[i - 1][j - 1] + _sub(c, a[i - 1], b[j - 1])):
            pairs.append((a[i - 1], b[j - 1]))
            i, j = i - 1, j - 1
        elif i and math.isclose(d[i][j], d[i - 1][j] + indel):
            pairs.append((a[i - 1], EPS))
            i -= 1
        else:
            pairs.append((EPS, b[j - 1]))
            j -= 1
    pairs.reverse()
    return d[n][m], pairs


def _tokens_against(medoid: str, s: str, costs: SubCosts | None) -> tuple[dict[int, str], dict[int, str]]:
    """Map s onto medoid positions: (position -> token, gap -> inserted substring). Gap g sits before position g."""
    _, pairs = align(medoid, s, costs)
    pos: dict[int, str] = {}
    gaps: dict[int, str] = {}
    i = 0
    for m, x in pairs:
        if m == EPS:
            gaps[i] = gaps.get(i, "") + x
        else:
            pos[i] = x
            i += 1
    return pos, gaps


# ---------------------------------------------------------------- confusion network


@dataclass(frozen=True)
class NetSlot:
    index: int | None  # medoid digit index; None for an insertion slot
    gap: int | None  # for an insertion slot: the medoid position it precedes
    votes: dict[str, dict[str, float]]  # token -> family -> weight (EPS = nothing here)

    @property
    def total(self) -> float:
        return sum(sum(f.values()) for f in self.votes.values())

    def weight(self, token: str) -> float:
        return sum(self.votes.get(token, {}).values())

    def ranked(self) -> list[tuple[str, float]]:
        return sorted(((t, self.weight(t)) for t in self.votes), key=lambda tw: (-tw[1], tw[0]))

    def logp(self, token: str) -> float:
        return math.log((self.weight(token) + NET_SMOOTHING) / (self.total + NET_SMOOTHING * NET_VOCAB))


@dataclass(frozen=True)
class ConfusionNetwork:
    medoid: str
    slots: tuple[NetSlot, ...]
    costs: SubCosts | None = None

    def distribution(self, index: int) -> dict[str, float]:
        """Vote share per digit at a medoid position (EPS for a deletion)."""
        for s in self.slots:
            if s.index == index:
                tot = s.total or 1.0
                return {t: w / tot for t, w in s.ranked()}
        raise IndexError(index)

    def logprob(self, digits: str) -> float:
        pos, gaps = _tokens_against(self.medoid, digits, self.costs)
        lp = 0.0
        seen_gaps: set[int] = set()
        for s in self.slots:
            if s.index is not None:
                lp += s.logp(pos.get(s.index, EPS))
            else:
                assert s.gap is not None
                seen_gaps.add(s.gap)
                lp += s.logp(gaps.get(s.gap, EPS))
        unseen = [g for g in gaps if g not in seen_gaps]
        total = max((s.total for s in self.slots), default=0.0)
        lp += len(unseen) * math.log(NET_SMOOTHING / (total + NET_SMOOTHING * NET_VOCAB))
        return lp

    def contested(self) -> tuple[int, ...]:
        return tuple(s.index for s in self.slots if s.index is not None and len(s.votes) > 1)

    def top_paths(self, k: int) -> list[tuple[str, float]]:
        """Best k distinct valid phone numbers through the network by summed vote log-probability."""
        opts = [[(t, s.logp(t)) for t, _ in s.ranked()] for s in self.slots]
        if not opts or k <= 0:
            return []
        start: tuple[int, ...] = (0,) * len(opts)

        def cost(idx: tuple[int, ...]) -> float:
            return -sum(opts[n][i][1] for n, i in enumerate(idx))

        heap: list[tuple[float, tuple[int, ...]]] = [(cost(start), start)]
        seen: set[tuple[int, ...]] = {start}
        out: dict[str, float] = {}
        pops = 0
        while heap and len(out) < k and pops < _MAX_PATH_POPS:
            c, idx = heapq.heappop(heap)
            pops += 1
            s = "".join(opts[n][i][0] for n, i in enumerate(idx))
            if is_valid("phone", s) and s not in out:
                out[s] = -c
            for n in range(len(idx)):
                if idx[n] + 1 < len(opts[n]):
                    nxt = idx[:n] + (idx[n] + 1,) + idx[n + 1 :]
                    if nxt not in seen:
                        seen.add(nxt)
                        heapq.heappush(heap, (cost(nxt), nxt))
        return sorted(out.items(), key=lambda sv: (-sv[1], sv[0]))


def medoid(strings: Sequence[tuple[str, float]], costs: SubCosts | None = None) -> str:
    """Weighted medoid of (string, weight) pairs; ties prefer a valid phone, then the smaller string."""
    distinct = sorted({s for s, _ in strings})

    def total(c: str) -> float:
        return sum(w * align(c, s, costs)[0] for s, w in strings)

    return min(distinct, key=lambda c: (round(total(c), 9), not is_valid("phone", c), c))


def build_network(
    weighted: Sequence[tuple[str, str, float]], costs: SubCosts | None = None
) -> ConfusionNetwork | None:
    """weighted: (digit string, family, weight). Each string is aligned to the medoid independently."""
    if not weighted:
        return None
    center = medoid([(s, w) for s, _, w in weighted], costs)
    mapped = [(_tokens_against(center, s, costs), fam, w) for s, fam, w in weighted]
    used_gaps = sorted({g for (_, gaps), _, _ in mapped for g in gaps})
    order: list[tuple[int | None, int | None]] = []
    for i in range(len(center) + 1):
        if i in used_gaps:
            order.append((None, i))
        if i < len(center):
            order.append((i, None))
    slots: list[NetSlot] = []
    for index, gap in order:
        votes: dict[str, dict[str, float]] = {}
        for (pos, gaps), fam, w in mapped:
            tok = pos.get(index, EPS) if index is not None else gaps.get(gap if gap is not None else -1, EPS)
            fam_votes = votes.setdefault(tok, {})
            fam_votes[fam] = fam_votes.get(fam, 0.0) + w
        slots.append(
            NetSlot(
                index=index, gap=gap, votes={t: dict(sorted(v.items())) for t, v in sorted(votes.items())}
            )
        )
    return ConfusionNetwork(medoid=center, slots=tuple(slots), costs=costs)


# ---------------------------------------------------------------- lattice


@dataclass(frozen=True)
class SlotLattice:
    slot: Slot
    proposed: Value | None
    candidates: tuple[Value, ...]  # ranked best first; always contains a well-formed proposed value
    support: dict[str, dict[str, float]]  # key(value) -> non-agent family -> share of that family's variants
    sources: dict[str, tuple[str, ...]]  # key(value) -> every source (agent included) that heard it
    families_present: tuple[str, ...]  # non-agent families with any hypothesis this turn
    families_heard: tuple[str, ...]  # non-agent families with some value for this slot
    unstable_families: tuple[str, ...]  # families whose variants heard different values
    multi_variant_families: tuple[str, ...]
    network: ConfusionNetwork | None = None
    path_logprob: dict[str, float] = field(default_factory=dict)  # phone: key -> network log-probability
    contested_positions: tuple[int, ...] = ()

    def support_weight(self, value: Value) -> float:
        return sum(self.support.get(key(value), {}).values())

    def supporting_families(self, value: Value) -> tuple[str, ...]:
        """Families where a strict majority of variants that heard a value heard this one."""
        return tuple(f for f, w in sorted(self.support.get(key(value), {}).items()) if w > 0.5)


def _family_shares(hyps: Sequence[Hypothesis], slot: Slot) -> dict[str, dict[str, float]]:
    """family -> key(value) -> share among that family's variants that produced a value."""
    by_fam: dict[str, list[Value]] = {}
    for h in hyps:
        v = canon(slot, h.values.get(slot))
        if v is not None:
            by_fam.setdefault(h.family, []).append(v)
    out: dict[str, dict[str, float]] = {}
    for fam, vals in by_fam.items():
        shares: dict[str, float] = {}
        for v in vals:
            shares[key(v)] = shares.get(key(v), 0.0) + 1.0 / len(vals)
        out[fam] = shares
    return out


def sorted_hypotheses(hyps: Iterable[Hypothesis]) -> tuple[Hypothesis, ...]:
    """Canonical order so nothing downstream depends on arrival order."""
    return tuple(
        sorted(
            hyps, key=lambda h: (h.family, h.source, h.text, sorted((k, str(v)) for k, v in h.values.items()))
        )
    )


def build(
    evidence: Evidence, slot: Slot, max_candidates: int = 8, costs: SubCosts | None = None
) -> SlotLattice:
    hyps = sorted_hypotheses(evidence.hypotheses)
    others = [h for h in hyps if h.family != AGENT_FAMILY]
    proposed = canon(slot, evidence.proposed.get(slot))

    values: dict[str, Value] = {}
    sources: dict[str, list[str]] = {}
    for h in hyps:
        v = canon(slot, h.values.get(slot))
        if v is None:
            continue
        sources.setdefault(key(v), []).append(h.source)
        if is_valid(slot, v):
            values.setdefault(key(v), v)
    if proposed is not None:
        values.setdefault(key(proposed), proposed)

    shares = _family_shares(others, slot)
    support: dict[str, dict[str, float]] = {}
    for fam in sorted(shares):
        for k, w in shares[fam].items():
            support.setdefault(k, {})[fam] = w

    variant_count: dict[str, int] = {}
    for h in others:
        variant_count[h.family] = variant_count.get(h.family, 0) + 1
    multi = tuple(sorted(f for f, n in variant_count.items() if n > 1))
    unstable = tuple(sorted(f for f in multi if len(shares.get(f, {})) > 1))

    network: ConfusionNetwork | None = None
    path_lp: dict[str, float] = {}
    if slot == "phone":
        weighted: list[tuple[str, str, float]] = []
        for h in others:
            v = canon(slot, h.values.get(slot))
            if isinstance(v, str):
                n_valued = sum(
                    1 for g in others if g.family == h.family and canon(slot, g.values.get(slot)) is not None
                )
                weighted.append((v, h.family, 1.0 / n_valued))
        network = build_network(weighted, costs)
        if network is not None:
            for s, _ in network.top_paths(max_candidates):
                values.setdefault(s, s)
            path_lp = {k: network.logprob(k) for k in values if k.isdigit()}

    def rank(k: str) -> tuple[float, float, int, str]:
        sup = sum(support.get(k, {}).values())
        return (-round(sup, 9), -round(path_lp.get(k, 0.0), 9), -len(sources.get(k, [])), k)

    ranked = sorted(values, key=rank)
    keep = ranked[:max_candidates]
    if proposed is not None and key(proposed) not in keep:
        keep = keep[: max(max_candidates - 1, 0)] + [key(proposed)]
        keep.sort(key=rank)
    candidates = tuple(values[k] for k in keep)

    if network is not None:
        contested = network.contested()
    else:
        top = [c for c in candidates[:3] if len(str(c)) == len(str(candidates[0]))] if candidates else []
        contested = differing_positions(top) if slot != "weekday" else ()

    return SlotLattice(
        slot=slot,
        proposed=proposed,
        candidates=candidates,
        support={k: support[k] for k in sorted(support)},
        sources={k: tuple(sorted(v)) for k, v in sorted(sources.items())},
        families_present=tuple(sorted(variant_count)),
        families_heard=tuple(sorted(shares)),
        unstable_families=unstable,
        multi_variant_families=multi,
        network=network,
        path_logprob={k: path_lp[k] for k in sorted(path_lp) if k in keep},
        contested_positions=contested,
    )
