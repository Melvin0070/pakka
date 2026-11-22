"""Acoustic witness: an open Hindi CTC model scores the exact value about to be executed.

Model: ONNX export of AI4Bharat IndicConformer Hindi (CTC head, 256 subword pieces + blank), run on CPU
with onnxruntime. The front-end (NeMo log-mel) and every CTC computation are numpy, so nothing here
needs torch, and cached log-probs make offline evaluation model-free.

Scoring is likelihood-ratio verification, an old idea (1990s IVR digit grammars); the only twist is
what it verifies: another model's tool-call argument.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import time
import unicodedata
from dataclasses import dataclass

import numpy as np

from . import lang as languages
from .types import DIGIT_SLOTS, Slot, WitnessScore

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models" / "hi"
CACHE_DIR = ROOT / "data" / "witness_cache"
MODEL_NAME = "ai4bharat/indicconformer-hi-ctc (OpenVoiceOS ONNX)"

SAMPLE_RATE = 16000
N_FFT, WIN, HOP, N_MELS = 512, 400, 160, 80
FRAME_S = HOP * 4 / SAMPLE_RATE  # encoder subsamples by 4: one output frame per 40 ms
NEG = -1e30


# ---------------------------------------------------------------- front-end


def _mel_filterbank() -> np.ndarray:
    """Slaney-scale, area-normalised triangles: what librosa.filters.mel gives NeMo by default."""

    def hz_to_mel(f: np.ndarray) -> np.ndarray:
        f = np.asarray(f, dtype=np.float64)
        lin = f / (200.0 / 3)
        log = 15.0 + np.log(np.maximum(f, 1e-9) / 1000.0) / (np.log(6.4) / 27.0)
        return np.where(f >= 1000.0, log, lin)

    def mel_to_hz(m: np.ndarray) -> np.ndarray:
        lin = m * (200.0 / 3)
        log = 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0))
        return np.where(m >= 15.0, log, lin)

    fft_freqs = np.linspace(0, SAMPLE_RATE / 2, N_FFT // 2 + 1)
    edges = mel_to_hz(np.linspace(hz_to_mel(np.array(0.0)), hz_to_mel(np.array(SAMPLE_RATE / 2)), N_MELS + 2))
    lower = (fft_freqs[None, :] - edges[:-2, None]) / np.diff(edges)[:-1, None]
    upper = (edges[2:, None] - fft_freqs[None, :]) / np.diff(edges)[1:, None]
    fb = np.maximum(0.0, np.minimum(lower, upper))
    fb *= (2.0 / (edges[2:] - edges[:-2]))[:, None]
    return fb.astype(np.float32)


_FB: np.ndarray | None = None


def log_mel(audio: np.ndarray) -> np.ndarray:
    """NeMo AudioToMelSpectrogramPreprocessor defaults: preemphasis 0.97, 25 ms Hann, 10 ms hop,
    log power mel, per-feature mean/variance normalisation. Returns [80, frames]."""
    global _FB
    if _FB is None:
        _FB = _mel_filterbank()
    x = audio.astype(np.float32)
    x = np.concatenate([x[:1], x[1:] - 0.97 * x[:-1]])
    x = np.pad(x, N_FFT // 2, mode="reflect")
    window = np.zeros(N_FFT, dtype=np.float32)
    off = (N_FFT - WIN) // 2
    window[off : off + WIN] = np.hanning(WIN)
    n_frames = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    power = np.abs(np.fft.rfft(x[idx] * window, axis=1)) ** 2
    mel = np.log(power @ _FB.T + 2.0**-24).T
    mean = mel.mean(axis=1, keepdims=True)
    std = mel.std(axis=1, ddof=1, keepdims=True) + 1e-5
    return ((mel - mean) / std).astype(np.float32)


# ---------------------------------------------------------------- CTC on a graph


def logsumexp(a: np.ndarray, axis: int | None = None) -> np.ndarray:
    m = np.max(a, axis=axis, keepdims=True)
    out = m + np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True))
    return np.squeeze(out, axis=axis)


@dataclass(frozen=True)
class Arc:
    """A subword piece between two graph nodes. `group` labels which part of the sentence it belongs to."""

    start: int
    end: int
    token: int
    group: int = 0


@dataclass(frozen=True)
class Graph:
    """CTC state graph. State emissions index a [T, V+1] matrix whose last column is the filler."""

    emit: np.ndarray  # [S] column per state
    preds: np.ndarray  # [S, K] predecessor state indexes, padded with S (a dummy -inf state)
    initial: np.ndarray  # [S] bool
    final: np.ndarray  # [S] bool
    group: np.ndarray  # [S] the arc's group, -1 for blanks and fillers


def build_graph(
    arcs: list[Arc], n_nodes: int, blank: int, star: bool = False, final_node: int | None = None
) -> Graph:
    """Arcs form a DAG from node 0 to `final_node` (default: the last node). States are one blank per
    node plus one per arc. Summing over paths marginalises the alignment and every alternative the DAG
    encodes: segmentations into pieces, spelling variants, Hindi or English digit words."""
    last = n_nodes - 1 if final_node is None else final_node
    n = n_nodes + len(arcs)
    star_l, star_r = n, n + 1
    total = n + (2 if star else 0)
    ending: dict[int, list[int]] = {}
    for i, a in enumerate(arcs):
        ending.setdefault(a.end, []).append(n_nodes + i)

    pred_lists: list[list[int]] = [[p, *ending.get(p, [])] for p in range(n_nodes)]
    for i, a in enumerate(arcs):
        # A repeated piece must pass through blank, otherwise CTC collapses the two into one.
        pred_lists.append(
            [n_nodes + i, a.start]
            + [s for s in ending.get(a.start, []) if arcs[s - n_nodes].token != a.token]
        )
    initial = np.zeros(total, dtype=bool)
    final = np.zeros(total, dtype=bool)
    initial[0] = final[last] = True
    for i, a in enumerate(arcs):
        initial[n_nodes + i] |= a.start == 0
        final[n_nodes + i] |= a.end == last
    if star:
        initial[star_l] = final[star_r] = True
        pred_lists.append([star_l])
        pred_lists[0].append(star_l)
        for i, a in enumerate(arcs):
            if a.start == 0:
                pred_lists[n_nodes + i].append(star_l)
        pred_lists.append([star_r, last, *ending.get(last, [])])
    k = max(len(p) for p in pred_lists)
    preds = np.full((total, k), total, dtype=np.int64)
    for s, p in enumerate(pred_lists):
        preds[s, : len(p)] = p
    emit = np.array([blank] * n_nodes + [a.token for a in arcs] + ([blank + 1] * 2 if star else []))
    group = np.array([-1] * n_nodes + [a.group for a in arcs] + ([-1] * 2 if star else []))
    return Graph(emit=emit, preds=preds, initial=initial, final=final, group=group)


def _with_filler(log_probs: np.ndarray, filler: str) -> np.ndarray:
    if filler == "free":  # filler emits anything with probability 1
        col = np.zeros((log_probs.shape[0], 1), dtype=np.float64)
    elif filler == "max":  # filler costs what the model's own best label costs: a background model
        col = log_probs.max(axis=1, keepdims=True)
    else:
        raise ValueError(filler)
    return np.concatenate([log_probs.astype(np.float64), col], axis=1)


def graph_loglik(log_probs: np.ndarray, g: Graph, filler: str = "free") -> float:
    """log of the total probability of all paths through the graph (CTC forward, log space)."""
    em = _with_filler(log_probs, filler)[:, g.emit]  # [T, S]
    alpha = np.where(g.initial, em[0], NEG)
    for t in range(1, em.shape[0]):
        prev = np.append(alpha, NEG)[g.preds]
        alpha = logsumexp(prev, axis=1) + em[t]
    return float(logsumexp(alpha[g.final]))


def graph_viterbi(log_probs: np.ndarray, g: Graph, filler: str = "free") -> list[int]:
    """Best single path: state index per frame."""
    em = _with_filler(log_probs, filler)[:, g.emit]
    n_frames, n_states = em.shape
    alpha = np.where(g.initial, em[0], NEG)
    back = np.zeros((n_frames, n_states), dtype=np.int64)
    for t in range(1, n_frames):
        prev = np.append(alpha, NEG)[g.preds]
        best = prev.argmax(axis=1)
        back[t] = g.preds[np.arange(n_states), best]
        alpha = prev[np.arange(n_states), best] + em[t]
    s = int(np.where(g.final, alpha, NEG).argmax())
    path = [s]
    for t in range(n_frames - 1, 0, -1):
        s = int(back[t, s])
        path.append(s)
    return path[::-1]


def _linear(token_ids: list[int]) -> tuple[list[Arc], int]:
    return [Arc(i, i + 1, t) for i, t in enumerate(token_ids)], len(token_ids) + 1


def ctc_loglik(log_probs: np.ndarray, token_ids: list[int], blank: int | None = None) -> float:
    """log p(token sequence | audio): exact CTC forward. Blank defaults to the last column."""
    b = log_probs.shape[1] - 1 if blank is None else blank
    arcs, n = _linear(token_ids)
    return graph_loglik(log_probs, build_graph(arcs, n, b))


def ctc_loglik_star(
    log_probs: np.ndarray, token_ids: list[int], blank: int | None = None, filler: str = "free"
) -> float:
    """CTC forward with a wildcard on both sides, so a phrase is scored wherever it occurs.

    filler="free" gives log sum over spans of p(phrase | span); "max" charges the frames outside the
    span at the model's best-label cost, which stops short phrases from winning by explaining less audio.
    """
    b = log_probs.shape[1] - 1 if blank is None else blank
    arcs, n = _linear(token_ids)
    return graph_loglik(log_probs, build_graph(arcs, n, b, star=True), filler)


# ---------------------------------------------------------------- text <-> pieces

_SPACE = "▁"
# An edge of a phrase DAG: (from node, to node, words, group). Parallel edges are alternatives.
Edge = tuple[int, int, str, int]
LEFT, CANDIDATE, RIGHT = 0, 1, 2


# Spellings the model uses interchangeably for one spoken word. Summed over, so that a candidate is
# not penalised for our choice of orthography.
def spellings(word: str, lang: languages.Lang = languages.HI) -> list[str]:
    forms = [word, *lang.spellings.get(word, ())]
    if lang.code == "hi":
        forms += [f.replace("ँ", "ं") for f in forms]  # chandrabindu is often written as anusvara
        forms += [f.replace("़", "") for f in forms]  # nukta is often dropped
    return list(dict.fromkeys(forms))


def text_edges(text: str, start: int = 0, group: int = 0) -> tuple[list[Edge], int]:
    """A plain sentence as a chain of one-word edges. Returns (edges, end node)."""
    words = text.split()
    return [(start + i, start + i + 1, w, group) for i, w in enumerate(words)], start + len(words)


def phone_edges(
    digits: str, start: int = 0, group: int = CANDIDATE, lang: languages.Lang = languages.HI
) -> tuple[list[Edge], int]:
    """Digit grammar: each digit in the native language or English, plus "double x" and "triple x" over
    repeats. Callers mix all of these inside one number, so whole-string renderings cannot cover them."""
    edges: list[Edge] = []
    for i, d in enumerate(digits):
        words = lang.digit_words[int(d)]
        edges += [(start + i, start + i + 1, w, group) for w in words]
        for run, prefix in zip((2, 3), lang.repeat_words, strict=True):
            if digits[i : i + run] == d * run:
                edges += [(start + i, start + i + run, f"{prefix} {w}", group) for w in words]
    return edges, start + len(digits)


class Pieces:
    """The model's subword vocabulary. No SentencePiece model ships with the ONNX export, so the
    training-time segmentation cannot be reproduced; instead every segmentation becomes a path in the
    graph and the CTC forward sums over them, which is the exact string likelihood under the model."""

    def __init__(self, vocab: list[str], lang: languages.Lang = languages.HI):
        self.vocab = vocab
        self.lang = lang
        self.blank = len(vocab) - 1
        self.index = {p: i for i, p in enumerate(vocab) if 0 < i < self.blank}
        self.chars = {c for p in self.index for c in p}
        self.max_len = max(len(p) for p in self.index)

    @classmethod
    def load(cls, path: pathlib.Path, lang: languages.Lang = languages.HI) -> Pieces:
        vocab = [line.rsplit(" ", 1)[0] for line in path.read_text(encoding="utf8").splitlines() if line]
        return cls(vocab, lang)

    def clean_word(self, word: str) -> str:
        form = unicodedata.normalize(self.lang.unicode_form, word)
        return "".join(c for c in form if c in self.chars and c != _SPACE)

    def prepare(self, text: str) -> str:
        return "".join(_SPACE + w for w in map(self.clean_word, text.split()) if w)

    def compile(self, edges: list[Edge], end: int, variants: bool = True) -> tuple[list[Arc], int, int]:
        """Phrase DAG -> piece arcs. Returns (arcs, n_nodes, final_node)."""
        arcs: list[Arc] = []
        n_nodes = end + 1

        def fresh() -> int:
            nonlocal n_nodes
            n_nodes += 1
            return n_nodes - 1

        for u, v, phrase, group in edges:
            words = [w for w in phrase.split() if self.clean_word(w)]
            if not words:
                raise ValueError(f"no scorable characters in {phrase!r}; filter with scorable() first")
            bounds = [u, *(fresh() for _ in words[1:]), v]
            for k, word in enumerate(words):
                for form in spellings(word, self.lang) if variants else [word]:
                    s = _SPACE + self.clean_word(form)
                    local = [bounds[k], *(fresh() for _ in s[1:]), bounds[k + 1]]
                    for i in range(len(s)):
                        for j in range(i + 1, min(len(s), i + self.max_len) + 1):
                            if s[i:j] in self.index:
                                arcs.append(Arc(local[i], local[j], self.index[s[i:j]], group))
        return arcs, n_nodes, end

    def scorable(self, text: str) -> str:
        """Drop words with no characters in the vocabulary (Latin script, punctuation)."""
        return " ".join(w for w in text.split() if self.clean_word(w))

    def tokenize(self, text: str) -> list[int]:
        """Fewest-pieces segmentation. One reasonable path through the lattice, for callers that need
        a single sequence; scoring uses every segmentation."""
        s = self.prepare(text)
        best: list[tuple[int, int, int] | None] = [None] * (len(s) + 1)  # (count, prev, token)
        best[0] = (0, -1, -1)
        for j in range(1, len(s) + 1):
            for i in range(max(0, j - self.max_len), j):
                prev, cur = best[i], best[j]
                if prev is not None and s[i:j] in self.index and (cur is None or prev[0] + 1 < cur[0]):
                    best[j] = (prev[0] + 1, i, self.index[s[i:j]])
        out: list[int] = []
        j = len(s)
        while j > 0:
            node = best[j]
            assert node is not None, f"cannot tokenise {text!r}"
            out.append(node[2])
            j = node[1]
        return out[::-1]

    def decode(self, token_ids: list[int]) -> str:
        text = "".join(self.vocab[t] for t in token_ids).replace(_SPACE, " ").strip()
        return unicodedata.normalize("NFC", text)


# ---------------------------------------------------------------- the witness


class Witness:
    def __init__(
        self,
        model_dir: pathlib.Path | None = None,
        cache_dir: pathlib.Path | None = CACHE_DIR,
        int8: bool = False,
        threads: int = 0,
        lang: str | None = None,
    ):
        self.language = languages.get(lang)
        self.lang = self.language.code
        self.model_dir = model_dir or self.language.model_dir
        self.cache_dir, self.int8, self.threads = cache_dir, int8, threads
        self._session = None
        self._pieces: Pieces | None = None

    @property
    def pieces(self) -> Pieces:
        if self._pieces is None:
            self._pieces = Pieces.load(self.model_dir / "vocab.txt", self.language)
        return self._pieces

    @property
    def variant(self) -> str:
        return "int8" if self.int8 else "fp32"

    def _run(self, feats: np.ndarray) -> np.ndarray:
        if self._session is None:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = self.threads
            name = "model.int8.onnx" if self.int8 else "model.onnx"
            self._session = ort.InferenceSession(
                str(self.model_dir / name), opts, providers=["CPUExecutionProvider"]
            )
        out = self._session.run(
            None, {"audio_signal": feats[None], "length": np.array([feats.shape[1]], dtype=np.int64)}
        )
        return np.asarray(out[0])[0]

    def log_probs(self, pcm16: np.ndarray, sample_rate: int) -> np.ndarray:
        """[T, V] per-frame log-probabilities, blank last. Cached on disk by audio hash."""
        pcm16 = np.ascontiguousarray(pcm16, dtype=np.int16)
        # Hindi keeps the key it had before other languages existed, so its cached posteriors stay valid.
        tag = self.variant if self.lang == "hi" else f"{self.variant}|{self.lang}"
        key = hashlib.sha256(pcm16.tobytes() + f"|{sample_rate}|{tag}".encode()).hexdigest()[:32]
        path = self.cache_dir / f"{key}.npy" if self.cache_dir else None
        if path and path.exists():
            return np.load(path)
        audio = pcm16.astype(np.float32) / 32768.0
        if sample_rate != SAMPLE_RATE:
            import soxr

            audio = soxr.resample(audio, sample_rate, SAMPLE_RATE)
        lp = self._run(log_mel(audio)).astype(np.float32)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, lp)
        return lp

    def greedy(self, log_probs: np.ndarray) -> str:
        ids = log_probs.argmax(axis=1)
        keep = [int(t) for i, t in enumerate(ids) if t != self.pieces.blank and (i == 0 or t != ids[i - 1])]
        return self.pieces.decode(keep)

    def tokenize(self, text: str) -> list[int]:
        return self.pieces.tokenize(text)

    def _graph(self, slot: str, value: str, rendering: str, context: tuple[str, str] | None) -> Graph:
        p = self.pieces
        edges, node = text_edges(p.scorable(context[0]), 0, LEFT) if context else ([], 0)
        if slot in DIGIT_SLOTS and value.isdigit():
            cand, node = phone_edges(value, node, lang=self.language)
        else:
            cand, node = text_edges(p.scorable(rendering), node, CANDIDATE)
        tail, node = text_edges(p.scorable(context[1]), node, RIGHT) if context else ([], node)
        arcs, n_nodes, final = p.compile(edges + cand + tail, node)
        return build_graph(arcs, n_nodes, p.blank, star=context is None, final_node=final)

    def text_loglik(self, log_probs: np.ndarray, text: str, star: bool = False, filler: str = "max") -> float:
        """log p(text | audio), summed over alignments, segmentations and spelling variants."""
        p = self.pieces
        edges, end = text_edges(p.scorable(text))
        arcs, n_nodes, final = p.compile(edges, end)
        return graph_loglik(
            log_probs, build_graph(arcs, n_nodes, p.blank, star=star, final_node=final), filler
        )

    def score_slot(
        self,
        log_probs: np.ndarray,
        slot: Slot,
        candidates: dict[str, list[str]],
        context: tuple[str, str] | None = None,
        filler: str = "max",
    ) -> WitnessScore:
        """Score every candidate value on the same audio.

        candidates: str(value) -> spoken renderings (pramaan.render.renderings).
        context=(left, right): each rendering is scored as the full sentence left + rendering + right,
        identical around every candidate, by exact CTC. context=None: the rendering alone, with a
        filler either side. Phone values ignore the renderings and use the digit grammar.
        """
        t0 = time.perf_counter()
        loglik: dict[str, float] = {}
        best: dict[str, str] = {}
        for value, forms in candidates.items():
            if slot in DIGIT_SLOTS and value.isdigit():
                forms = forms[:1] or [value]
            scores = [
                graph_loglik(log_probs, self._graph(slot, value, form, context), filler) for form in forms
            ]
            loglik[value] = float(logsumexp(np.array(scores)))
            best[value] = forms[int(np.argmax(scores))]
        return WitnessScore(
            slot=slot,
            loglik=loglik,
            best_rendering=best,
            latency_ms=(time.perf_counter() - t0) * 1000,
            model=f"{self.language.model_name} {self.variant}",
        )

    def align_span(
        self,
        log_probs: np.ndarray,
        slot: Slot,
        value: str,
        rendering: str,
        context: tuple[str, str] | None = None,
        filler: str = "max",
    ) -> tuple[float, float] | None:
        """(start_s, end_s) of the candidate on the best path, for highlighting in the UI."""
        g = self._graph(slot, value, rendering, context)
        frames = [t for t, s in enumerate(graph_viterbi(log_probs, g, filler)) if g.group[s] == CANDIDATE]
        if not frames:
            return None
        return frames[0] * FRAME_S, (frames[-1] + 1) * FRAME_S


def describe() -> str:
    return json.dumps({"model": MODEL_NAME, "frame_s": FRAME_S, "mels": N_MELS})
