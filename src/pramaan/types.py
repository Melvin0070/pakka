"""Boundary objects. Every module exchanges these and nothing else.

Money is integer rupees, phone is a 10-digit string, weekday is a lowercase English name,
day_of_month is an int 1-31. No floats for values.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Slot = Literal["amount_rupees", "day_of_month", "weekday", "phone"]
SLOTS: tuple[Slot, ...] = ("amount_rupees", "day_of_month", "weekday", "phone")
Value = int | str
Values = dict[str, Value]  # slot -> typed value; a missing key means "no value heard"

# A family is the unit of independence. Variants of one model count as one voter.
Family = Literal["openai-realtime", "openai-transcribe", "elevenlabs", "sarvam", "ai4bharat", "verbx"]


def canonical_json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Word(Frozen):
    text: str
    start_s: float | None = None
    end_s: float | None = None
    logprob: float | None = None


class Hypothesis(Frozen):
    """One recogniser's reading of a turn. `values` is filled by the normaliser, never by the source."""

    source: str  # e.g. "gpt-transcribe", "gpt-transcribe+hints", "gpt-4o-transcribe", "scribe", "saaras"
    family: Family
    text: str
    latency_ms: float
    words: tuple[Word, ...] = ()  # token or word level, with logprobs where the vendor exposes them
    values: Values = Field(default_factory=dict)
    # Lowest logprob among the tokens/words that produced each slot's value; absent if not exposed.
    value_min_logprob: dict[str, float] = Field(default_factory=dict)


class WitnessScore(Frozen):
    """CTC log-likelihood of candidate values for one slot, all scored on the same audio in identical context."""

    slot: Slot
    loglik: dict[str, float]  # str(value) -> log p(rendering(s) of value | audio), logsumexp over renderings
    best_rendering: dict[str, str] = Field(default_factory=dict)
    latency_ms: float = 0.0
    model: str = ""


class Evidence(Frozen):
    """Everything decide() may look at. Sources that missed the deadline are simply not in `hypotheses`."""

    audio_sha: str
    proposed: Values  # the tool-call arguments the agent wants to execute
    hypotheses: tuple[Hypothesis, ...] = ()
    witness: tuple[WitnessScore, ...] = ()
    absent_sources: tuple[str, ...] = ()  # configured but late or failed


class Verdict(StrEnum):
    PASS = "pass"  # evidence supports the proposed value: execute
    ASK = "ask"  # evidence is split between a few candidates: one forced-choice question
    BLOCK = "block"  # proposed value has no support and no clear alternative: ask caller to repeat


class SlotDecision(Frozen):
    slot: Slot
    proposed: Value | None
    verdict: Verdict
    reason: str  # short machine code, e.g. "families_agree", "proposed_unsupported", "witness_prefers_other"
    candidates: tuple[
        Value, ...
    ] = ()  # ranked, best first; includes the proposed value when it is a candidate
    posterior: dict[str, float] = Field(default_factory=dict)  # str(value) -> probability over candidates
    score: float = 0.0  # monotone confidence that `proposed` is right; the gate thresholds this
    supporting_families: tuple[str, ...] = ()
    witness_llr: float | None = None  # loglik(proposed) - loglik(best other candidate)
    contested_positions: tuple[int, ...] = ()  # digit indexes (phone) or decimal places that differ
    # The value to execute when the verdict is PASS: the proposed one, or the repair the evidence supports.
    final: Value | None = None


class Decision(Frozen):
    verdict: Verdict  # worst over slots: BLOCK > ASK > PASS
    slots: tuple[SlotDecision, ...]
    score: float  # min over slot scores
    execute: Values = Field(default_factory=dict)  # arguments to run on PASS, repairs applied
    question: str | None = None  # forced-choice question in Hinglish for the least certain slot
    question_slot: Slot | None = None
    policy_hash: str = ""


class Policy(Frozen):
    """Frozen before calibration; its hash goes in every bundle and in the README."""

    version: str = "p1"
    deadline_ms: float = 1200.0
    accept_threshold: float = 0.5  # lambda*: slot score at or above this passes
    min_families: int = 2  # hard predicate: independent families that must support the proposed value
    require_witness: bool = True  # hard predicate: witness must be present and not contradict
    witness_llr_min: float = 0.0  # witness must not prefer another candidate by more than this (nats)
    max_candidates: int = 8
    # Hold the action when enough families agree on a value the agent left out of the tool call.
    guard_omissions: bool = True
    # Replace the agent's value when exactly one other candidate passes every test the proposal failed.
    repair: bool = True
    # The acoustic model is Hindi. On a turn the transcribers wrote entirely in English it neither votes
    # nor vetoes, and the decision rests on the recogniser families alone.
    language_aware: bool = False
    # score = sigmoid(bias + sum(weights[f] * feature[f])); features defined in score.py
    weights: dict[str, float] = Field(default_factory=dict)
    bias: float = 0.0
    code_commit: str = ""

    @property
    def hash(self) -> str:
        d = self.model_dump()
        if not d["language_aware"]:
            del d["language_aware"]  # keeps the hash of policies frozen before the field existed
        return sha256_hex(canonical_json(d))[:12]


class LedgerState(StrEnum):
    PROPOSED = "proposed"
    HELD = "held"
    ASKED = "asked"
    COMMITTED = "committed"
    VOIDED = "voided"


class Bundle(Frozen):
    """Content-addressed record of one decision. Audio is referenced by hash, never embedded."""

    turn_id: str
    evidence: Evidence
    decision: Decision
    policy_hash: str
    prev: str = ""  # id of the previous bundle: a hash chain
    created_at: str = ""  # ISO time, set by the shell, excluded from the id

    @property
    def id(self) -> str:
        return sha256_hex(canonical_json(self.model_dump(exclude={"created_at"})))[:16]
