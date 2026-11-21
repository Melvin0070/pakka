import asyncio

import pytest

from pramaan.cache import Cache, CacheMiss


def test_round_trip_and_latency_preserved(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"text": "पच्चीस", "n": 1}

    e1 = asyncio.run(c.cached("a" * 64, "src", {"model": "m"}, fn))
    e2 = asyncio.run(c.cached("a" * 64, "src", {"model": "m"}, fn))
    assert calls == 1
    assert not e1.hit and e2.hit
    assert e2.response == {"text": "पच्चीस", "n": 1}
    assert e2.latency_ms == e1.latency_ms >= 15
    # Param order must not matter; param values must.
    assert c.get("a" * 64, "src", {"model": "m"}) is not None
    assert c.get("a" * 64, "src", {"model": "m2"}) is None


def test_reopen_persists(tmp_path):
    Cache(tmp_path / "c.sqlite").put("s", "src", {"a": 1, "b": 2}, [1, 2], 12.34)
    e = Cache(tmp_path / "c.sqlite").get("s", "src", {"b": 2, "a": 1})
    assert e is not None and e.response == [1, 2] and e.latency_ms == 12.3


def test_offline_miss_raises(tmp_path, monkeypatch):
    c = Cache(tmp_path / "c.sqlite")
    c.put("hit", "src", {}, {"ok": True}, 5.0)
    monkeypatch.setenv("PRAMAAN_OFFLINE", "1")

    async def fn():
        raise AssertionError("network must not be called offline")

    assert asyncio.run(c.cached("hit", "src", {}, fn)).response == {"ok": True}
    with pytest.raises(CacheMiss):
        asyncio.run(c.cached("miss", "src", {}, fn))


def test_permanent_errors_cached_and_droppable(tmp_path):
    c = Cache(tmp_path / "c.sqlite")

    async def boom():
        raise ValueError("bad request")

    e = asyncio.run(c.cached("s", "src", {}, boom, cache_errors=ValueError))
    assert e.is_error and c.get("s", "src", {}) is not None
    assert c.delete_errors() == 1 and c.get("s", "src", {}) is None


def test_timed_response_reports_own_latency(tmp_path):
    from pramaan.cache import Timed

    c = Cache(tmp_path / "c.sqlite")

    async def fn():
        await asyncio.sleep(0.05)  # e.g. backoff before the successful attempt
        return Timed({"text": "x"}, 7.0)

    e = asyncio.run(c.cached("s", "src", {}, fn))
    assert e.response == {"text": "x"} and e.latency_ms == 7.0
    assert c.get("s", "src", {}).latency_ms == 7.0
