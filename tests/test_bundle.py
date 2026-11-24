import json

import pytest

from pakka.bundle import BundleStore, ChainError, ReplayMismatch, make_bundle, masked, replay, verify_chain
from pakka.decide import decide
from pakka.types import Bundle, Evidence, Hypothesis, Policy, Verdict, WitnessScore

POLICY = Policy()


def evidence(i=0):
    hs = (
        Hypothesis(
            source="gt",
            family="openai-transcribe",
            text="mera number 9876543210 hai",
            latency_ms=300,
            values={"phone": "9876543210", "amount_rupees": 2750 + i},
        ),
        Hypothesis(
            source="scribe",
            family="elevenlabs",
            text="9876543710",
            latency_ms=400,
            values={"phone": "9876543710", "amount_rupees": 2750 + i},
        ),
        Hypothesis(
            source="saaras",
            family="sarvam",
            text="",
            latency_ms=500,
            values={"phone": "9876543210", "amount_rupees": 2750 + i},
        ),
    )
    return Evidence(
        audio_sha=f"a{i}",
        proposed={"phone": "9876543210", "amount_rupees": 2750 + i},
        hypotheses=hs,
        witness=(
            WitnessScore(
                slot="phone",
                loglik={"9876543210": -4.0, "9876543710": -3.0},
                best_rendering={"9876543210": "nau aath"},
            ),
            WitnessScore(slot="amount_rupees", loglik={str(2750 + i): -1.0}),
        ),
    )


def bundle(i=0):
    ev = evidence(i)
    return make_bundle(f"t{i}", ev, decide(ev, POLICY), created_at="2026-11-21T20:00:00")


def test_chain_appends_and_verifies(tmp_path):
    path = tmp_path / "b.jsonl"
    store = BundleStore(path)
    first = store.append(bundle(0))
    second = store.append(bundle(1))
    assert first.prev == "" and second.prev == first.id
    assert verify_chain(path) == 2
    assert BundleStore(path).last_id == second.id
    assert [b.id for b in store.load()] == [first.id, second.id]


def test_id_excludes_created_at():
    a = bundle(0)
    assert a.id == a.model_copy(update={"created_at": "later"}).id


def test_tampering_breaks_chain(tmp_path):
    path = tmp_path / "b.jsonl"
    store = BundleStore(path)
    for i in range(3):
        store.append(bundle(i))
    lines = path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["bundle"]["evidence"]["proposed"]["amount_rupees"] = 9999
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ChainError, match="bundle 2"):
        verify_chain(path)


def test_dropped_line_breaks_chain(tmp_path):
    path = tmp_path / "b.jsonl"
    store = BundleStore(path)
    for i in range(3):
        store.append(bundle(i))
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n" + lines[2] + "\n")
    with pytest.raises(ChainError, match="prev"):
        verify_chain(path)


def test_masked_view_keeps_only_contested_digits():
    b = bundle(0)
    phone = next(s for s in b.decision.slots if s.slot == "phone")
    assert phone.verdict == Verdict.ASK and phone.contested_positions == (7,)
    m = masked(b)
    assert m["evidence"]["proposed"]["phone"] == "•••••••2••"
    assert m["evidence"]["hypotheses"][0]["text"] == "mera number •••••••••• hai"
    assert all("98765" not in json.dumps(s) for s in m["decision"]["slots"])
    assert m["evidence"]["proposed"]["amount_rupees"] == 2750
    assert "nau aath" not in json.dumps(m)


def test_replay_roundtrip_through_json(tmp_path):
    path = tmp_path / "b.jsonl"
    BundleStore(path).append(bundle(0))
    (stored,) = BundleStore(path).load()
    assert replay(stored, POLICY) == stored.decision


def test_replay_detects_mismatch():
    b = bundle(0)
    with pytest.raises(ReplayMismatch, match="policy"):
        replay(b, Policy(accept_threshold=0.9))
    forged = Bundle.model_validate(
        {**b.model_dump(), "decision": {**b.decision.model_dump(), "verdict": "pass"}}
    )
    with pytest.raises(ReplayMismatch, match="verdict"):
        replay(forged, POLICY)


def test_a_line_torn_by_a_crash_is_dropped_and_the_chain_continues(tmp_path):
    path = tmp_path / "b.jsonl"
    first = BundleStore(path).append(bundle(0))
    with path.open("a") as fh:
        fh.write('{"id": "abc", "bundle": {"turn_')
    store = BundleStore(path)
    assert store.last_id == first.id
    store.append(bundle(1))
    assert verify_chain(path) == 2
