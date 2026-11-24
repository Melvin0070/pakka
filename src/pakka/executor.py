"""The ledger and sole tool runner. PROPOSED -> HELD -> ASKED -> COMMITTED | VOIDED.

Rows are unique on (session_id, operation, entity_version). `operation` names the business operation
(tool + a stable key such as the booking id), never a response or call id: a regenerated tool call maps to
the same row, so it cannot execute twice. A caller correction bumps entity_version and voids what was
outstanding; a cancelled or incomplete response voids the rows it proposed.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .types import LedgerState, Values, canonical_json, sha256_hex

ToolFn = Callable[[Values], Any]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops (
  session_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  entity_version INTEGER NOT NULL,
  state TEXT NOT NULL,
  args TEXT NOT NULL,
  value_hash TEXT NOT NULL,
  bundle_id TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  token TEXT NOT NULL,
  response_id TEXT NOT NULL,
  outcome TEXT,
  PRIMARY KEY (session_id, operation, entity_version)
);
CREATE TABLE IF NOT EXISTS versions (
  session_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  version INTEGER NOT NULL,
  PRIMARY KEY (session_id, operation)
);
"""
_OPEN = (LedgerState.PROPOSED, LedgerState.HELD, LedgerState.ASKED)


class LedgerError(Exception):
    pass


class StaleToken(LedgerError):
    """Token was never issued, or was superseded by new arguments or a correction."""


class Voided(LedgerError):
    pass


class BadTransition(LedgerError):
    pass


def operation_name(tool: str, stable_key: str) -> str:
    return f"{tool}:{stable_key}"


def value_hash(args: Values) -> str:
    return sha256_hex(canonical_json(args))


def confirmation_token(vhash: str, bundle_id: str, policy_hash: str, entity_version: int) -> str:
    return sha256_hex(canonical_json([vhash, bundle_id, policy_hash, entity_version]))[:32]


@dataclass(frozen=True)
class Entry:
    session_id: str
    operation: str
    entity_version: int
    state: LedgerState
    args: Values
    value_hash: str
    bundle_id: str
    policy_hash: str
    token: str
    response_id: str
    outcome: Any = None


class Ledger:
    def __init__(self, path: str = ":memory:") -> None:
        # Autocommit mode so every mutation is an explicit BEGIN IMMEDIATE transaction: the write lock
        # is taken before the state is read, which serialises concurrent commits across connections.
        self._db = sqlite3.connect(path, isolation_level=None, timeout=30.0)
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------ reads

    def version(self, session_id: str, operation: str) -> int:
        row = self._db.execute(
            "SELECT version FROM versions WHERE session_id=? AND operation=?", (session_id, operation)
        ).fetchone()
        return int(row[0]) if row else 1

    def get(self, session_id: str, operation: str, entity_version: int | None = None) -> Entry | None:
        v = entity_version if entity_version is not None else self.version(session_id, operation)
        row = self._db.execute(
            "SELECT session_id, operation, entity_version, state, args, value_hash, bundle_id, policy_hash, token,"
            " response_id, outcome FROM ops WHERE session_id=? AND operation=? AND entity_version=?",
            (session_id, operation, v),
        ).fetchone()
        return _entry(row) if row else None

    def entries(self, session_id: str | None = None) -> list[Entry]:
        sql = (
            "SELECT session_id, operation, entity_version, state, args, value_hash, bundle_id, policy_hash, token,"
            " response_id, outcome FROM ops"
        )
        rows = (
            self._db.execute(sql + " WHERE session_id=? ORDER BY operation, entity_version", (session_id,))
            if session_id is not None
            else self._db.execute(sql + " ORDER BY session_id, operation, entity_version")
        )
        return [_entry(r) for r in rows]

    # ------------------------------------------------------------ writes

    def propose(
        self,
        session_id: str,
        operation: str,
        args: Values,
        *,
        bundle_id: str = "",
        policy_hash: str = "",
        response_id: str = "",
    ) -> Entry:
        """Record or refresh the pending call for this operation's current version.

        A committed row is returned unchanged (the retry gets the stored outcome). An open or voided row
        takes the new arguments and a fresh token, so any token for the old arguments goes stale.
        """
        with self._txn():
            v = self.version(session_id, operation)
            vh = value_hash(args)
            tok = confirmation_token(vh, bundle_id, policy_hash, v)
            self._db.execute(
                "INSERT INTO ops VALUES (?,?,?,?,?,?,?,?,?,?,NULL)"
                " ON CONFLICT (session_id, operation, entity_version) DO UPDATE SET"
                " state=excluded.state, args=excluded.args, value_hash=excluded.value_hash,"
                " bundle_id=excluded.bundle_id, policy_hash=excluded.policy_hash, token=excluded.token,"
                " response_id=excluded.response_id WHERE ops.state != ?",
                (
                    session_id, operation, v, LedgerState.PROPOSED, canonical_json(args).decode(), vh,
                    bundle_id, policy_hash, tok, response_id, LedgerState.COMMITTED,
                ),
            )  # fmt: skip
            entry = self.get(session_id, operation, v)
        assert entry is not None
        return entry

    def hold(self, session_id: str, operation: str, token: str) -> Entry:
        return self._move(
            session_id, operation, token, LedgerState.HELD, (LedgerState.PROPOSED, LedgerState.ASKED)
        )

    def ask(self, session_id: str, operation: str, token: str) -> Entry:
        return self._move(
            session_id, operation, token, LedgerState.ASKED, (LedgerState.PROPOSED, LedgerState.HELD)
        )

    def commit(self, session_id: str, operation: str, token: str, tool: ToolFn) -> Any:
        """Run the tool at most once for this token's row; a repeat returns the stored outcome.

        If the tool raises, the transaction rolls back and the row stays open for a retry.
        """
        with self._txn():
            entry = self._by_token(session_id, operation, token)
            if entry.state == LedgerState.COMMITTED:
                return entry.outcome
            if entry.state == LedgerState.VOIDED:
                raise Voided(f"{session_id}/{operation} v{entry.entity_version} was voided")
            outcome = tool(dict(entry.args))
            self._db.execute(
                "UPDATE ops SET state=?, outcome=? WHERE session_id=? AND operation=? AND entity_version=?",
                (
                    LedgerState.COMMITTED,
                    # Must not raise: the tool has run, and a rollback here would let it run again.
                    json.dumps(outcome, default=repr),
                    session_id,
                    operation,
                    entry.entity_version,
                ),
            )
            return outcome

    def correct(self, session_id: str, operation: str) -> int:
        """The caller corrected a value: open rows are voided and the next proposal is a new entity version."""
        with self._txn():
            v = self.version(session_id, operation) + 1
            self._db.execute(
                "INSERT INTO versions VALUES (?,?,?) ON CONFLICT (session_id, operation) DO UPDATE SET version=excluded.version",
                (session_id, operation, v),
            )
            self._void_where("session_id=? AND operation=? AND entity_version<?", (session_id, operation, v))
            return v

    def void_response(self, session_id: str, response_id: str) -> int:
        """A cancelled or incomplete response: void every open row it proposed."""
        if not response_id:  # rows proposed without a response id are not one response
            return 0
        with self._txn():
            return self._void_where("session_id=? AND response_id=?", (session_id, response_id))

    def void(self, session_id: str, operation: str) -> int:
        with self._txn():
            return self._void_where("session_id=? AND operation=?", (session_id, operation))

    # ------------------------------------------------------------ internals

    def _txn(self) -> _Txn:
        return _Txn(self._db)

    def _void_where(self, where: str, params: tuple[object, ...]) -> int:
        cur = self._db.execute(
            f"UPDATE ops SET state=? WHERE {where} AND state IN (?,?,?)",
            (LedgerState.VOIDED, *params, *_OPEN),
        )
        return cur.rowcount

    def _by_token(self, session_id: str, operation: str, token: str) -> Entry:
        entry = self.get(session_id, operation)
        if entry is None or entry.token != token:
            raise StaleToken(f"{session_id}/{operation}: token is not current")
        return entry

    def _move(
        self, session_id: str, operation: str, token: str, to: LedgerState, allowed: tuple[LedgerState, ...]
    ) -> Entry:
        with self._txn():
            entry = self._by_token(session_id, operation, token)
            if entry.state not in allowed:
                raise BadTransition(f"{entry.state} -> {to}")
            self._db.execute(
                "UPDATE ops SET state=? WHERE session_id=? AND operation=? AND entity_version=?",
                (to, session_id, operation, entry.entity_version),
            )
            moved = self.get(session_id, operation, entry.entity_version)
        assert moved is not None
        return moved


class _Txn:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db
        self._nested = False

    def __enter__(self) -> None:
        self._nested = self._db.in_transaction
        if not self._nested:
            self._db.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._nested:
            return
        self._db.execute("ROLLBACK" if exc_type else "COMMIT")


def _entry(row: tuple[Any, ...]) -> Entry:
    return Entry(
        session_id=row[0],
        operation=row[1],
        entity_version=int(row[2]),
        state=LedgerState(row[3]),
        args=json.loads(row[4]),
        value_hash=row[5],
        bundle_id=row[6],
        policy_hash=row[7],
        token=row[8],
        response_id=row[9],
        outcome=json.loads(row[10]) if row[10] is not None else None,
    )
