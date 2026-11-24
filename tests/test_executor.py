import threading
from collections import Counter

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from pakka.executor import (
    BadTransition,
    Ledger,
    StaleToken,
    Voided,
    confirmation_token,
    operation_name,
    value_hash,
)
from pakka.types import LedgerState

OP = operation_name("book_payment", "promise-1")


class Tool:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, args):
        self.calls.append(dict(args))
        return {"ok": True, "n": len(self.calls)}


def test_happy_path_and_retry_returns_stored_outcome():
    led, tool = Ledger(), Tool()
    e = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b1", policy_hash="p", response_id="r1")
    assert e.state == LedgerState.PROPOSED
    assert e.token == confirmation_token(value_hash({"amount_rupees": 2750}), "b1", "p", 1)
    led.hold("s", OP, e.token)
    assert led.commit("s", OP, e.token, tool) == {"ok": True, "n": 1}
    assert led.commit("s", OP, e.token, tool) == {"ok": True, "n": 1}
    again = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b1", policy_hash="p", response_id="r2")
    assert again.state == LedgerState.COMMITTED and again.outcome == {"ok": True, "n": 1}
    assert len(tool.calls) == 1


def test_regenerated_call_with_new_ids_cannot_execute_twice():
    led, tool = Ledger(), Tool()
    a = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b1", response_id="resp-1")
    led.commit("s", OP, a.token, tool)
    b = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b2", response_id="resp-2")
    assert b.state == LedgerState.COMMITTED
    with pytest.raises(StaleToken):
        led.commit("s", OP, confirmation_token(value_hash({"amount_rupees": 2750}), "b2", "", 1), tool)
    assert len(tool.calls) == 1


def test_barge_in_voids_and_regeneration_revives():
    led, tool = Ledger(), Tool()
    a = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b1", response_id="r1")
    led.ask("s", OP, a.token)
    assert led.void_response("s", "r1") == 1
    with pytest.raises(Voided):
        led.commit("s", OP, a.token, tool)
    b = led.propose("s", OP, {"amount_rupees": 3750}, bundle_id="b2", response_id="r2")
    with pytest.raises(StaleToken):
        led.commit("s", OP, a.token, tool)
    led.commit("s", OP, b.token, tool)
    assert tool.calls == [{"amount_rupees": 3750}]


def test_correction_bumps_version_and_voids_tokens():
    led, tool = Ledger(), Tool()
    a = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b1")
    assert led.correct("s", OP) == 2
    assert led.get("s", OP, 1).state == LedgerState.VOIDED
    with pytest.raises(StaleToken):
        led.commit("s", OP, a.token, tool)
    b = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b1")
    assert b.entity_version == 2 and b.token != a.token
    led.commit("s", OP, b.token, tool)
    assert len(tool.calls) == 1


def test_changed_arguments_invalidate_old_token():
    led, tool = Ledger(), Tool()
    a = led.propose("s", OP, {"amount_rupees": 2750})
    led.propose("s", OP, {"amount_rupees": 3750})
    with pytest.raises(StaleToken):
        led.commit("s", OP, a.token, tool)
    assert tool.calls == []


def test_tool_failure_rolls_back_and_can_retry():
    led = Ledger()
    e = led.propose("s", OP, {"amount_rupees": 1})

    def boom(_):
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        led.commit("s", OP, e.token, boom)
    assert led.get("s", OP).state == LedgerState.PROPOSED
    tool = Tool()
    led.commit("s", OP, e.token, tool)
    assert len(tool.calls) == 1


def test_bad_transition():
    led = Ledger()
    e = led.propose("s", OP, {"amount_rupees": 1})
    led.commit("s", OP, e.token, Tool())
    with pytest.raises(BadTransition):
        led.hold("s", OP, e.token)


def test_concurrent_commits_execute_once(tmp_path):
    path = str(tmp_path / "ledger.db")
    e = Ledger(path).propose("s", OP, {"amount_rupees": 2750})
    tool = Tool()
    lock = threading.Lock()

    def locked(args):
        with lock:
            return tool(args)

    def worker():
        Ledger(path).commit("s", OP, e.token, locked)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(tool.calls) == 1


class LedgerMachine(RuleBasedStateMachine):
    """Random barge-ins, retries, regenerations and corrections: each entity version executes at most once,
    and nothing executes on a token that was not current."""

    def __init__(self):
        super().__init__()
        self.led = Ledger()
        self.executed: list[tuple[str, int, int]] = []  # (op, version, amount)
        self.tokens: list[tuple[str, str, int]] = []  # every token ever issued: (op, token, version)
        self.response = 0

    def tool_for(self, op):
        def run(args):
            self.executed.append((op, self.led.version("s", op), args["amount_rupees"]))
            return {"amount": args["amount_rupees"]}

        return run

    @rule(
        op=st.sampled_from(["pay:1", "pay:2"]),
        amount=st.sampled_from([2750, 3750]),
        bundle=st.sampled_from(["b1", "b2"]),
    )
    def propose(self, op, amount, bundle):
        self.response += 1
        e = self.led.propose(
            "s", op, {"amount_rupees": amount}, bundle_id=bundle, response_id=f"r{self.response}"
        )
        self.tokens.append((op, e.token, e.entity_version))

    @rule(data=st.data())
    def commit_some_token(self, data):
        if not self.tokens:
            return
        op, tok, version = data.draw(st.sampled_from(self.tokens))
        current = self.led.get("s", op)
        before = len(self.executed)
        try:
            self.led.commit("s", op, tok, self.tool_for(op))
        except (StaleToken, Voided):
            assert len(self.executed) == before
            return
        assert current is not None and current.token == tok and version == current.entity_version
        if current.state == LedgerState.COMMITTED:
            assert len(self.executed) == before

    @rule(op=st.sampled_from(["pay:1", "pay:2"]))
    def correct(self, op):
        self.led.correct("s", op)

    @rule(data=st.data())
    def barge_in(self, data):
        if self.response:
            self.led.void_response("s", f"r{data.draw(st.integers(1, self.response))}")

    @rule(data=st.data())
    def ask_or_hold(self, data):
        if not self.tokens:
            return
        op, tok, _ = data.draw(st.sampled_from(self.tokens))
        try:
            (self.led.ask if data.draw(st.booleans()) else self.led.hold)("s", op, tok)
        except (StaleToken, BadTransition):
            pass

    @invariant()
    def at_most_once_per_version(self):
        per = Counter((op, v) for op, v, _ in self.executed)
        assert all(n == 1 for n in per.values())
        committed = [e for e in self.led.entries("s") if e.state == LedgerState.COMMITTED]
        assert len(committed) == len(self.executed)


LedgerMachine.TestCase.settings = settings(max_examples=60, stateful_step_count=40, deadline=None)
TestLedgerMachine = LedgerMachine.TestCase


def test_an_outcome_json_cannot_hold_still_runs_the_tool_once():
    led, calls = Ledger(), []

    def tool(args):
        calls.append(args)
        return {"at": object(), 1: "mixed", "k": "keys"}

    e = led.propose("s", OP, {"amount_rupees": 2750}, bundle_id="b1")
    led.commit("s", OP, e.token, tool)
    led.commit("s", OP, e.token, tool)
    assert len(calls) == 1


def test_void_response_without_an_id_voids_nothing():
    led = Ledger()
    led.propose("s", "op-a", {"amount_rupees": 1})
    led.propose("s", "op-b", {"amount_rupees": 2})
    assert led.void_response("s", "") == 0
