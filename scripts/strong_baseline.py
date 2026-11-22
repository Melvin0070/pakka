"""Does the model-alone result survive a better prompt? Reruns locked set 2 with number-specific instructions.

The prompt was written once, after this set's earlier results had been seen, and is not tuned. Its worked examples avoid every amount in
this set, so it cannot be answering from the test values. Responses go to their own cache so the evidence
behind `make eval` cannot change. The frozen policy is applied unchanged. Usage: make strong-baseline
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

import numpy as np

from eval.common import DELTA, FRESH2_EVIDENCE, RESULTS, ROOT, Outcome, Row, guard, split
from eval.common import load as load_rows
from pramaan import audio
from pramaan.cache import Cache
from pramaan.evidence import assemble
from pramaan.gate import cp_upper
from pramaan.pipeline import load_policy
from pramaan.sources import realtime_agent as ra
from pramaan.sources.base import PermanentError, with_retries
from pramaan.types import Evidence
from pramaan.witness import Witness

CACHE = ROOT / "data" / "cache.strong.sqlite"
INSTRUCTIONS = (
    "You are an assistant answering a phone call in India. Callers speak Hindi, English or a mix, often on a "
    "poor line. Accuracy of spoken numbers is your most important job, because the values you log are acted on. "
    "Listen to the whole utterance, then call log_commitment with every amount, date, weekday and phone number "
    "the caller actually said, and leave the others null.\n"
    "Amounts: convert to plain integer rupees. सवा means plus a quarter, साढ़े plus a half, पौने minus a quarter, "
    "डेढ़ is 1.5 and ढाई is 2.5 of the unit that follows: सवा छह लाख = 625000, साढ़े आठ करोड़ = 85000000, "
    "पौने नौ लाख = 875000, डेढ़ करोड़ = 15000000, ढाई करोड़ = 25000000. बहत्तर सौ = 7200. लाख = 100000, "
    "करोड़ = 10000000. Hindi numbers one short of a ten begin with उन (उनतालीस is 39, उनचास is 49). Distinguish "
    "thirteen from thirty and similar pairs carefully.\n"
    "Phone numbers: write exactly the digits spoken, in order, in any mix of Hindi and English. Double seven "
    "means 77 and triple five means 555. Never invent, drop or reorder a digit."
)
TOOL = copy.deepcopy(ra.TOOL)
TOOL["parameters"]["properties"]["amount_rupees"]["description"] = (
    "Exact amount in rupees as a plain integer, after applying सवा, साढ़े, पौने, डेढ़, ढाई, सौ, हज़ार, लाख and करोड़."
)
PARAMS = {**ra.PARAMS, "instructions": INSTRUCTIONS, "tool": TOOL}


def test_rows() -> list[dict]:
    test = {r.clip_id for r in split(load_rows(FRESH2_EVIDENCE)[0])[1]}
    return [r for r in map(json.loads, FRESH2_EVIDENCE.read_text().splitlines()) if r["clip_id"] in test]


def paths() -> dict[str, Path]:
    rows = map(json.loads, (FRESH2_EVIDENCE.parent / "manifest.jsonl").read_text().splitlines())
    return {r["clip_id"]: ROOT / r["path"] for r in rows}


async def agent(cache: Cache, pcm: bytes, sha: str) -> ra.AgentProposal | None:
    e = await cache.cached(
        sha, ra.NAME, PARAMS, lambda: with_retries(lambda: ra._call(pcm, PARAMS)), cache_errors=PermanentError
    )
    return None if e.is_error else ra.parse(e.response, e.latency_ms)


async def collect() -> None:
    cache, where, sem = Cache(CACHE), paths(), asyncio.Semaphore(4)
    rows, failed = test_rows(), 0

    async def one(r: dict) -> None:
        nonlocal failed
        async with sem:
            try:
                pcm = audio.read_pcm24k(where[r["clip_id"]])
                failed += await agent(cache, pcm, r["evidence"]["audio_sha"]) is None
            except Exception as ex:
                failed += 1
                print(f"{r['clip_id']}: {type(ex).__name__}: {str(ex)[:160]}")

    await asyncio.gather(*map(one, rows))
    print(f"{len(rows)} clips, {failed} failed")
    sys.exit(1 if failed else 0)


async def score() -> None:
    cache, where, witness, policy = Cache(CACHE), paths(), Witness(), load_policy()
    out, n, failed = [], 0, 0
    tally = dict.fromkeys(("old_wrong", "new_wrong", "p_wrong", "p_asked", "p_broke_right"), 0)
    for r in test_rows():
        pcm = audio.read_pcm24k(where[r["clip_id"]])
        old = Evidence(**r["evidence"])
        p = await agent(cache, pcm, old.audio_sha)
        if p is None:
            failed += 1
            continue
        kept = [h for h in old.hypotheses if h.family != "ai4bharat"]
        absent = [a for a in old.absent_sources if a != "indicconformer-greedy"]
        lp = witness.log_probs(np.frombuffer(pcm, dtype=np.int16), audio.RATE)
        ev = assemble(old.audio_sha, p.values, kept, absent, witness, lp, 0.0)
        row = Row(
            r["clip_id"],
            r["speaker"],
            r["condition"],
            r["truth"],
            p.response_ms or r["agent_response_ms"],
            ev,
        )
        o: Outcome = guard(row, policy)
        new_wrong = dict(p.values) != r["truth"]
        n += 1
        tally["old_wrong"] += dict(old.proposed) != r["truth"]
        tally["new_wrong"] += new_wrong
        tally["p_wrong"] += o.executed and o.wrong
        tally["p_asked"] += not o.executed
        tally["p_broke_right"] += not new_wrong and o.executed and o.wrong
        out.append({"clip_id": r["clip_id"], "truth": r["truth"], "agent": p.values, "guard_executed": o.executed, "guard_wrong": o.wrong})  # fmt: skip
    accepted = n - tally["p_asked"]
    # Same shape as the run_eval results, so the overview screen can show this set directly.
    view = {
        "arms": [
            {"id": "A", "n": n, "wrong_silent": tally["new_wrong"], "asked": 0},
            {"id": "P", "n": n, "wrong_silent": tally["p_wrong"], "asked": tally["p_asked"]},
        ],
        "certificate": {"upper_bound": round(cp_upper(tally["p_wrong"], accepted, DELTA), 4)},
        "dataset": {"n_actions": n, "n_speakers": len({c["clip_id"].split("_")[0] for c in out})},
    }
    result = {"set": "locked set 2, test speakers", "policy": policy.hash, "n": n, "failed": failed, **tally, **view, "instructions": INSTRUCTIONS, "clips": out}  # fmt: skip
    (RESULTS / "strong_baseline.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("clips", "instructions")}))


if __name__ == "__main__":
    if sys.argv[1:] not in (["collect"], ["score"]):
        sys.exit("usage: python -m scripts.strong_baseline collect|score")
    asyncio.run(collect() if sys.argv[1] == "collect" else score())
