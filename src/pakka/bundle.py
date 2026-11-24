"""Evidence bundles: content-addressed, append-only JSONL with a hash chain, a masked UI view, and replay."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .decide import decide
from .types import Bundle, Decision, Evidence, Policy, canonical_json

MASK = "•"
_DIGIT_RUN = re.compile(r"\d{6,}")


class ChainError(Exception):
    pass


class ReplayMismatch(Exception):
    pass


def make_bundle(
    turn_id: str, evidence: Evidence, decision: Decision, prev: str = "", created_at: str = ""
) -> Bundle:
    return Bundle(
        turn_id=turn_id,
        evidence=evidence,
        decision=decision,
        policy_hash=decision.policy_hash,
        prev=prev,
        created_at=created_at,
    )


def _line(b: Bundle) -> str:
    return canonical_json({"id": b.id, "bundle": b.model_dump(mode="json")}).decode()


def iter_bundles(path: str | Path) -> Iterator[tuple[str, Bundle]]:
    p = Path(path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as fh:
        for n, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
                yield rec["id"], Bundle.model_validate(rec["bundle"])
            except (ValueError, KeyError, TypeError) as e:
                raise ChainError(f"line {n}: unreadable: {e}") from e


class BundleStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._last = ""
        self._drop_torn_tail()
        for bid, _ in iter_bundles(self.path):
            self._last = bid

    def _drop_torn_tail(self) -> None:
        """A process killed mid-append leaves a last line with no newline; it was never acknowledged."""
        if not self.path.exists():
            return
        data = self.path.read_bytes()
        if data and not data.endswith(b"\n"):
            self.path.write_bytes(data[: data.rfind(b"\n") + 1])

    @property
    def last_id(self) -> str:
        return self._last

    def append(self, bundle: Bundle) -> Bundle:
        """Links the bundle to the current head and appends it; returns the stored, chained bundle."""
        chained = bundle.model_copy(update={"prev": self._last})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_line(chained) + "\n")
        self._last = chained.id
        return chained

    def load(self) -> list[Bundle]:
        return [b for _, b in iter_bundles(self.path)]


def verify_chain(path: str | Path) -> int:
    """Number of bundles if every id matches its content and every `prev` the line before; raises ChainError."""
    prev = ""
    count = 0
    for n, (bid, b) in enumerate(iter_bundles(path), start=1):
        if b.id != bid:
            raise ChainError(f"bundle {n}: stored id {bid} != content id {b.id}")
        if b.prev != prev:
            raise ChainError(f"bundle {n}: prev {b.prev!r} != {prev!r}")
        prev = bid
        count += 1
    return count


# ---------------------------------------------------------------- masked view


def _mask_digits(s: str, keep: set[int]) -> str:
    return "".join(c if (i in keep or not c.isdigit()) else MASK for i, c in enumerate(s))


def _mask_text(s: str) -> str:
    return _DIGIT_RUN.sub(lambda m: MASK * len(m.group()), s)


def masked(bundle: Bundle) -> dict[str, Any]:
    """JSON view for the UI: phone digits masked except contested positions; long digit runs in text masked."""
    phone_sd = next((sd for sd in bundle.decision.slots if sd.slot == "phone"), None)
    keep = set(phone_sd.contested_positions) if phone_sd else set()

    def ph(v: Any) -> Any:
        return _mask_digits(str(v), keep) if v is not None else None

    d = bundle.model_dump(mode="json")
    d["id"] = bundle.id
    ev = d["evidence"]
    if "phone" in ev["proposed"]:
        ev["proposed"]["phone"] = ph(ev["proposed"]["phone"])
    for h in ev["hypotheses"]:
        h["text"] = _mask_text(h["text"])
        h["words"] = [{**w, "text": _mask_text(w["text"])} for w in h["words"]]
        if "phone" in h["values"]:
            h["values"]["phone"] = ph(h["values"]["phone"])
    for w in ev["witness"]:
        if w["slot"] == "phone":
            w["loglik"] = [[ph(k), v] for k, v in w["loglik"].items()]
            w["best_rendering"] = {}
    for sd in d["decision"]["slots"]:
        if sd["slot"] == "phone":
            sd["proposed"] = ph(sd["proposed"])
            sd["candidates"] = [ph(c) for c in sd["candidates"]]
            # A list, since two numbers can mask to the same string.
            sd["posterior"] = [[ph(k), v] for k, v in sd["posterior"].items()]
    if d["decision"].get("question_slot") == "phone" and phone_sd and len(keep) != 1:
        d["decision"]["question"] = "[masked]"
    return d


# ---------------------------------------------------------------- replay


def replay(bundle: Bundle, policy: Policy) -> Decision:
    """Re-run decide on the stored evidence; raise ReplayMismatch unless it reproduces the stored decision."""
    if policy.hash != bundle.policy_hash:
        raise ReplayMismatch(f"policy hash {policy.hash} != bundle policy {bundle.policy_hash}")
    again = decide(bundle.evidence, policy)
    if again != bundle.decision:
        a, b = again.model_dump(mode="json"), bundle.decision.model_dump(mode="json")
        diff = sorted(k for k in a if a[k] != b.get(k))
        raise ReplayMismatch(f"turn {bundle.turn_id}: decision differs in {diff}")
    return again
