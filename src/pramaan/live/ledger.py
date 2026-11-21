"""The ledger as the live session uses it: one row per (session, operation, entity version).

`SqlLedger` adapts pramaan.executor (the durable, sole tool runner). `MemoryLedger` has the same
semantics with no storage and is what the session falls back to if the executor cannot be imported.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..types import LedgerState, Values

ToolFn = Callable[[Values], Any]
_OPEN = (LedgerState.PROPOSED, LedgerState.HELD, LedgerState.ASKED)


@dataclass
class Entry:
    session_id: str
    operation: str
    entity_version: int
    values: Values
    state: LedgerState = LedgerState.PROPOSED
    outcome: Any = None
    token: str = ""
    transitions: list[tuple[str, float, str]] = field(default_factory=list)  # (state, unix time, note)

    @property
    def id(self) -> str:
        return f"{self.operation}#v{self.entity_version}"

    def move(self, state: LedgerState, note: str = "") -> None:
        self.state = state
        self.transitions.append((state.value, time.time(), note))


class Ledger(Protocol):
    def propose(self, session_id: str, operation: str, values: Values) -> Entry:
        """Record or refresh the pending call for the current version. A committed row comes back as it is."""
        ...

    def hold(self, entry: Entry) -> None: ...
    def ask(self, entry: Entry, question: str) -> None: ...
    def commit(self, entry: Entry) -> tuple[bool, Any]:
        """Returns (executed_now, outcome). The tool runs at most once per row."""
        ...

    def void(self, entry: Entry, reason: str) -> None: ...
    def correct(self, session_id: str, operation: str) -> int:
        """The value may have changed: void what is open and start a new entity version."""
        ...


class MemoryLedger:
    def __init__(self, tool: ToolFn) -> None:
        self._tool = tool
        self._rows: dict[tuple[str, str, int], Entry] = {}
        self._versions: dict[tuple[str, str], int] = {}
        self.executions = 0

    def propose(self, session_id: str, operation: str, values: Values) -> Entry:
        v = self._versions.get((session_id, operation), 1)
        entry = self._rows.get((session_id, operation, v))
        if entry is None:
            entry = self._rows[(session_id, operation, v)] = Entry(session_id, operation, v, dict(values))
        elif entry.state == LedgerState.COMMITTED:
            return entry
        entry.values = dict(values)
        entry.move(LedgerState.PROPOSED)
        return entry

    def hold(self, entry: Entry) -> None:
        if entry.state in (LedgerState.PROPOSED, LedgerState.ASKED):
            entry.move(LedgerState.HELD)

    def ask(self, entry: Entry, question: str) -> None:
        if entry.state in (LedgerState.PROPOSED, LedgerState.HELD):
            entry.move(LedgerState.ASKED, question)

    def commit(self, entry: Entry) -> tuple[bool, Any]:
        if entry.state == LedgerState.COMMITTED:
            return False, entry.outcome
        if entry.state == LedgerState.VOIDED:
            raise ValueError("cannot commit a voided entry")
        entry.outcome = self._tool(dict(entry.values))
        self.executions += 1
        entry.move(LedgerState.COMMITTED)
        return True, entry.outcome

    def void(self, entry: Entry, reason: str) -> None:
        if entry.state in _OPEN:
            entry.move(LedgerState.VOIDED, reason)

    def correct(self, session_id: str, operation: str) -> int:
        key = (session_id, operation)
        v = self._versions[key] = self._versions.get(key, 1) + 1
        for (s, o, _), entry in self._rows.items():
            if (s, o) == key:
                self.void(entry, "superseded")
        return v


class SqlLedger:
    """pramaan.executor.Ledger behind the same interface; the executor stays the only thing that runs the tool."""

    def __init__(self, tool: ToolFn, path: str = ":memory:") -> None:
        from ..executor import Ledger as Executor

        self._ex = Executor(path)
        self._tool = tool
        self._rows: dict[tuple[str, str, int], Entry] = {}
        self.executions = 0

    def propose(self, session_id: str, operation: str, values: Values) -> Entry:
        row = self._ex.propose(session_id, operation, values)
        key = (session_id, operation, row.entity_version)
        entry = self._rows.get(key)
        if entry is None:
            entry = self._rows[key] = Entry(session_id, operation, row.entity_version, dict(row.args))
        entry.token, entry.values = row.token, dict(row.args)
        if row.state == LedgerState.COMMITTED:
            entry.outcome = row.outcome
            if entry.state != LedgerState.COMMITTED:
                entry.move(LedgerState.COMMITTED)
        else:
            entry.move(LedgerState.PROPOSED)
        return entry

    def hold(self, entry: Entry) -> None:
        if entry.state in (LedgerState.PROPOSED, LedgerState.ASKED):
            self._ex.hold(entry.session_id, entry.operation, entry.token)
            entry.move(LedgerState.HELD)

    def ask(self, entry: Entry, question: str) -> None:
        if entry.state in (LedgerState.PROPOSED, LedgerState.HELD):
            self._ex.ask(entry.session_id, entry.operation, entry.token)
            entry.move(LedgerState.ASKED, question)

    def commit(self, entry: Entry) -> tuple[bool, Any]:
        ran = False

        def once(values: Values) -> Any:
            nonlocal ran
            ran = True
            return self._tool(values)

        entry.outcome = self._ex.commit(entry.session_id, entry.operation, entry.token, once)
        if ran:
            self.executions += 1
        if entry.state != LedgerState.COMMITTED:
            entry.move(LedgerState.COMMITTED)
        return ran, entry.outcome

    def void(self, entry: Entry, reason: str) -> None:
        if entry.state in _OPEN:
            self._ex.void(entry.session_id, entry.operation)
            entry.move(LedgerState.VOIDED, reason)

    def correct(self, session_id: str, operation: str) -> int:
        v = self._ex.correct(session_id, operation)
        for (s, o, _), entry in self._rows.items():
            if (s, o) == (session_id, operation) and entry.state in _OPEN:
                entry.move(LedgerState.VOIDED, "superseded")
        return v


def make_ledger(tool: ToolFn, path: str = ":memory:") -> Ledger:
    try:
        return SqlLedger(tool, path)
    except ImportError:
        return MemoryLedger(tool)
