import itertools
import math

import numpy as np
import pytest

from pramaan.witness import (
    MODEL_DIR,
    Arc,
    Pieces,
    Witness,
    build_graph,
    ctc_loglik,
    ctc_loglik_star,
    graph_loglik,
    graph_viterbi,
    phone_edges,
    text_edges,
)

VOCAB = ["<unk>", "▁स", "ात", "▁सात", "▁", "स", "ा", "त", "आ", "ठ", "▁आठ", "<blk>"]


def random_log_probs(frames: int, vocab: int, seed: int = 0) -> np.ndarray:
    x = np.random.default_rng(seed).normal(size=(frames, vocab))
    return x - np.log(np.exp(x).sum(axis=1, keepdims=True))


def collapse(path: tuple[int, ...], blank: int) -> list[int]:
    return [t for i, t in enumerate(path) if t != blank and (i == 0 or t != path[i - 1])]


def brute_force(lp: np.ndarray, target: list[int]) -> float:
    blank = lp.shape[1] - 1
    total = 0.0
    for path in itertools.product(range(lp.shape[1]), repeat=lp.shape[0]):
        if collapse(path, blank) == target:
            total += math.exp(sum(lp[t, s] for t, s in enumerate(path)))
    return math.log(total)


@pytest.mark.parametrize("target", [[0], [1, 2], [1, 1], [2, 0, 2], [0, 0, 0]])
def test_ctc_forward_matches_enumeration(target):
    lp = random_log_probs(6, 4, seed=len(target))
    assert ctc_loglik(lp, target) == pytest.approx(brute_force(lp, target), abs=1e-9)


def test_impossible_sequence_has_no_mass():
    assert ctc_loglik(random_log_probs(2, 4), [1, 1]) < -1e20  # a repeat needs three frames


def test_star_matches_enumeration_over_spans():
    # With a free filler, the score is the sum over contiguous spans of p(phrase | span).
    lp = random_log_probs(5, 4, seed=3)
    target = [1, 2]
    spans = [ctc_loglik(lp[a:b], target) for a in range(5) for b in range(a + 1, 6)]
    expected = math.log(sum(math.exp(s) for s in spans if s > -1e20))
    assert ctc_loglik_star(lp, target, filler="free") == pytest.approx(expected, abs=1e-9)


def test_star_dominates_exact_and_grows_as_phrase_shrinks():
    lp = random_log_probs(12, 6, seed=1)
    full = [1, 3, 2, 4]
    assert ctc_loglik_star(lp, full, filler="free") >= ctc_loglik(lp, full)
    assert ctc_loglik_star(lp, full[1:3], filler="free") >= ctc_loglik_star(lp, full, filler="free")
    assert ctc_loglik_star(lp, full, filler="free") >= ctc_loglik_star(lp, full, filler="max")


def test_tokeniser_round_trip_and_fewest_pieces():
    p = Pieces(VOCAB)
    assert p.decode(p.tokenize("सात आठ")) == "सात आठ"
    assert p.tokenize("सात") == [VOCAB.index("▁सात")]
    assert p.prepare("सात, 7 आठ!") == "▁सात▁आठ"


def test_lattice_sums_over_segmentations():
    p = Pieces(VOCAB)
    lp = random_log_probs(7, len(VOCAB), seed=2)
    edges, end = text_edges("सात")
    arcs, n, final = p.compile(edges, end, variants=False)
    got = graph_loglik(lp, build_graph(arcs, n, p.blank, final_node=final))
    ids = VOCAB.index
    segmentations = [
        [ids("▁सात")],
        [ids("▁स"), ids("ात")],
        [ids("▁स"), ids("ा"), ids("त")],
        [ids("▁"), ids("स"), ids("ात")],
        [ids("▁"), ids("स"), ids("ा"), ids("त")],
    ]
    expected = math.log(sum(math.exp(ctc_loglik(lp, s)) for s in segmentations))
    assert got == pytest.approx(expected, abs=1e-9)


def test_phone_grammar_covers_double_and_mixed_language():
    edges, end = phone_edges("9944")
    assert end == 4
    assert (0, 2, "डबल नौ", 1) in edges and (2, 4, "डबल फ़ोर", 1) in edges
    assert (0, 1, "नाइन", 1) in edges and (0, 1, "नौ", 1) in edges


def test_viterbi_path_is_a_valid_path():
    lp = random_log_probs(8, 5, seed=4)
    g = build_graph([Arc(0, 1, 1), Arc(1, 2, 2)], 3, blank=4)
    path = graph_viterbi(lp, g)
    assert g.initial[path[0]] and g.final[path[-1]]
    assert all(b in g.preds[a_next] for b, a_next in zip(path, path[1:], strict=False))
    assert collapse(tuple(int(g.emit[s]) for s in path), 4) == [1, 2]


@pytest.mark.skipif(not (MODEL_DIR / "vocab.txt").exists(), reason="model not downloaded")
def test_real_vocab_spells_nukta_and_digits():
    w = Witness(cache_dir=None)
    for text in ("पौने तीन हज़ार", "ज़ीरो फ़ाइव डबल नौ", "साढ़े बारह हज़ार"):
        assert w.pieces.decode(w.tokenize(text)) == text
