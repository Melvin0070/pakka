import asyncio
import json
from pathlib import Path

import pytest

from pakka.cache import Cache, CacheMiss
from pakka.sources import gpt4o_transcribe, gpt_transcribe, realtime_agent, saaras, scribe
from pakka.sources.base import PermanentError, Source
from pakka.sources.registry import gather
from pakka.types import Hypothesis

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_gpt_transcribe_fixture():
    f = fixture("gpt_transcribe.json")
    h = gpt_transcribe.plain().parse(f["response"], f["latency_ms"])
    assert h.source == "gpt-transcribe" and h.family == "openai-transcribe"
    assert h.text == f["response"]["text"].strip() and h.values == {} and h.words == ()
    assert gpt_transcribe.hinted().parse(f["response"], 1.0).source == "gpt-transcribe+hints"


def test_gpt4o_fixture_words_carry_logprobs():
    f = fixture("gpt4o_transcribe.json")
    h = gpt4o_transcribe.parse(f["response"], f["latency_ms"])
    assert h.source == "gpt-4o-transcribe" and h.values == {}
    assert len(h.words) == len(f["response"]["logprobs"]) > 0
    assert "".join(w.text for w in h.words).strip() == h.text
    assert all(w.logprob is not None and w.logprob <= 0 for w in h.words)


def test_realtime_fixture_normalises_arguments():
    f = fixture("realtime_agent.json")
    p = realtime_agent.parse(f["response"], f["latency_ms"])
    assert p.values == f["expect_values"]
    assert all(v is not None for v in p.values.values())
    assert p.latency_ms == f["latency_ms"]


def test_realtime_norm():
    assert realtime_agent.norm("phone", "+91 98765-43210") == "9876543210"
    assert realtime_agent.norm("weekday", " Tuesday ") == "tuesday"
    assert realtime_agent.norm("amount_rupees", "2750") == 2750
    assert realtime_agent.norm("day_of_month", None) is None


def test_scribe_compact_and_parse_doc_shape():
    # Shape from the public docs; not a recorded response (no key during the build).
    body = {
        "language_code": "hin",
        "text": "पच्चीस हज़ार",
        "words": [
            {"text": "पच्चीस", "start": 0.1, "end": 0.6, "type": "word", "logprob": -0.2},
            {"text": " ", "start": 0.6, "end": 0.65, "type": "spacing", "logprob": 0.0},
            {"text": "हज़ार", "start": 0.65, "end": 1.0, "type": "word", "logprob": -0.05},
        ],
    }
    h = scribe.parse(scribe.compact(body), 300.0)
    assert h.family == "elevenlabs" and [w.text for w in h.words] == ["पच्चीस", "हज़ार"]
    assert h.words[0].start_s == 0.1 and h.words[0].logprob == -0.2


def test_saaras_compact_and_parse_doc_shape():
    h = saaras.parse(
        saaras.compact({"request_id": "x", "transcript": " सत्रह तारीख ", "language_code": "hi-IN"}), 9.0
    )
    assert h.family == "sarvam" and h.text == "सत्रह तारीख" and h.words == ()


def _fake(name: str, cache: Cache, latency_s: float = 0.0, fail: bool = False) -> Source:
    async def call(pcm: bytes, params: dict) -> dict:
        await asyncio.sleep(latency_s)
        if fail:
            raise PermanentError("nope")
        return {"text": name}

    def parse(resp: dict, ms: float) -> Hypothesis:
        return Hypothesis(source=name, family="openai-transcribe", text=resp["text"], latency_ms=ms)

    return Source(name, "openai-transcribe", {"v": 1}, call, parse, cache=cache)


def test_gather_failures_and_deadline_replay(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    srcs = [_fake("fast", c), _fake("slow", c, latency_s=0.3), _fake("broken", c, fail=True)]
    hyps, absent = asyncio.run(gather(b"\0\0" * 100, None, srcs))
    assert [h.source for h in hyps] == ["fast", "slow"] and absent == ["broken"]
    # Replayed from cache instantly, the slow source is still dropped by its recorded latency.
    hyps, absent = asyncio.run(gather(b"\0\0" * 100, 150.0, srcs))
    assert [h.source for h in hyps] == ["fast"] and absent == ["slow", "broken"]


def test_gather_offline_hole_is_loud(tmp_path, monkeypatch):
    monkeypatch.setenv("PAKKA_OFFLINE", "1")
    c = Cache(tmp_path / "c.sqlite")
    with pytest.raises(ExceptionGroup) as ei:
        asyncio.run(gather(b"\0\0", None, [_fake("x", c)]))
    assert ei.group_contains(CacheMiss)


def test_verbx_fixture():
    from pakka.sources import verbx

    f = fixture("verbx.json")
    h = verbx.parse(f["response"], f["latency_ms"])
    assert h.source == "verbx-vocaline" and h.family == "verbx"
    assert h.text == f["response"]["text"].strip() and h.words == () and h.values == {}
    body = {
        "text": " सवा एक हज़ार ",
        "language": "hi",
        "confidence": 0.9,
        "model": "verbx-vocaline",
        "latency_ms": 500,
    }
    assert verbx.compact(body) == {"text": " सवा एक हज़ार ", "model": "verbx-vocaline", "server_ms": 500}
