"""Replay cache: every adapter response, keyed by (audio_sha, source, params_sha), with its original latency.

The DB is committed so `make eval` runs with no network. PRAMAAN_OFFLINE=1 turns any miss into CacheMiss.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .types import canonical_json, sha256_hex

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "cache.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
  audio_sha TEXT NOT NULL,
  source TEXT NOT NULL,
  params_sha TEXT NOT NULL,
  response TEXT NOT NULL,
  latency_ms REAL NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (audio_sha, source, params_sha)
) WITHOUT ROWID;
"""


class CacheMiss(RuntimeError):
    """Raised on a miss when PRAMAAN_OFFLINE=1. Deliberately not swallowed by adapters: an offline run
    with a hole in the cache must fail loudly, not silently drop a source."""


@dataclass(frozen=True)
class Entry:
    response: Any
    latency_ms: float
    created_at: str
    hit: bool = True

    @property
    def is_error(self) -> bool:
        return isinstance(self.response, dict) and "_error" in self.response


@dataclass(frozen=True)
class Timed:
    """Returned by `fn` to report its own latency, e.g. only the final attempt after retries and backoff."""

    response: Any
    latency_ms: float


def params_sha(params: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(params))[:16]


def offline() -> bool:
    return os.environ.get("PRAMAAN_OFFLINE", "") not in ("", "0", "false")


class Cache:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or os.environ.get("PRAMAAN_CACHE") or DEFAULT_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection, used from the event loop and its worker threads one call at a time; rollback journal (not WAL) so the
        # committed file is self-contained with no -wal sidecar.
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.executescript(_SCHEMA)

    def get(self, audio_sha: str, source: str, params: dict[str, Any]) -> Entry | None:
        row = self._db.execute(
            "SELECT response, latency_ms, created_at FROM responses WHERE audio_sha=? AND source=? AND params_sha=?",
            (audio_sha, source, params_sha(params)),
        ).fetchone()
        if row is None:
            return None
        return Entry(json.loads(row[0]), row[1], row[2])

    def put(
        self, audio_sha: str, source: str, params: dict[str, Any], response: Any, latency_ms: float
    ) -> Entry:
        created = datetime.now(UTC).isoformat(timespec="seconds")
        self._db.execute(
            "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?,?)",
            (
                audio_sha,
                source,
                params_sha(params),
                canonical_json(response).decode(),
                round(latency_ms, 1),
                created,
            ),
        )
        self._db.commit()
        return Entry(response, round(latency_ms, 1), created, hit=False)

    def delete_errors(self, source: str | None = None) -> int:
        q = "DELETE FROM responses WHERE response LIKE '{\"_error\"%'"
        cur = self._db.execute(q + (" AND source=?" if source else ""), (source,) if source else ())
        self._db.commit()
        return cur.rowcount

    def count(self) -> dict[str, int]:
        return dict(self._db.execute("SELECT source, COUNT(*) FROM responses GROUP BY source").fetchall())

    def close(self) -> None:
        self._db.close()

    async def cached(
        self,
        audio_sha: str,
        source: str,
        params: dict[str, Any],
        fn: Callable[[], Awaitable[Any]],
        *,
        cache_errors: type[BaseException] | tuple[type[BaseException], ...] = (),
    ) -> Entry:
        """Return the cached entry or run `fn`, timing it. Exceptions listed in `cache_errors` are stored as
        {"_error": ...} rows so a permanent failure replays as the same absence offline."""
        hit = self.get(audio_sha, source, params)
        if hit is not None:
            return hit
        if offline():
            raise CacheMiss(f"{source} {audio_sha[:12]} {params_sha(params)}")
        t0 = time.perf_counter()
        try:
            response = await fn()
        except cache_errors as e:
            response = {"_error": f"{type(e).__name__}: {str(e)[:300]}"}
        if isinstance(response, Timed):
            return self.put(audio_sha, source, params, response.response, response.latency_ms)
        return self.put(audio_sha, source, params, response, (time.perf_counter() - t0) * 1000)


_default: Cache | None = None


def default_cache() -> Cache:
    global _default
    if _default is None:
        _default = Cache()
    return _default
