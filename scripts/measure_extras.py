"""Score recorded PIN and account lines and spoken answers to a question, on the frozen policy.

Digit lines run the live agent schema against the guard. Answers are judged worst-case: the agent is assumed to
still hold the wrong option, so a right result means the caller's own words corrected it. The agent's turn after
a real question is not exercised here. Usage: make human-extras
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path

import numpy as np

from eval.common import ROOT, Row, guard
from pramaan import audio
from pramaan.cache import Cache
from pramaan.decide import decide, resolve_answer
from pramaan.evidence import assemble
from pramaan.live.tooling import LEFT_INSTRUCTIONS, TOOL
from pramaan.pipeline import load_policy
from pramaan.sources import realtime_agent as ra
from pramaan.sources.base import PermanentError, with_retries
from pramaan.sources.registry import gather
from pramaan.types import Asked, Verdict
from pramaan.witness import Witness

PARAMS = {**ra.PARAMS, "instructions": LEFT_INSTRUCTIONS, "tool": TOOL}


async def agent(cache: Cache, pcm: bytes, sha: str) -> ra.AgentProposal | None:
    e = await cache.cached(
        sha, ra.NAME, PARAMS, lambda: with_retries(lambda: ra._call(pcm, PARAMS)), cache_errors=PermanentError
    )
    return None if e.is_error else ra.parse(e.response, e.latency_ms)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/human/extras_manifest.jsonl")
    ap.add_argument("--out", default="results/human_extras.json")
    args = ap.parse_args()
    rows = [json.loads(x) for x in (ROOT / args.manifest).read_text().splitlines() if x.strip()]
    policy, witness = load_policy(), Witness()
    answer_policy = policy.model_copy(update={"require_witness": False, "accept_threshold": 0.0})
    cache = Cache(os.environ.get("PRAMAAN_EXTRAS_CACHE") or ROOT / "data" / "cache.extras.sqlite")
    digit_tally, answer_tally, clips = Counter(), Counter(), []
    for r in rows:
        pcm = audio.read_pcm24k(Path(ROOT / r["path"]))
        hyps, absent = await gather(pcm, None, audio_sha=r["audio_sha"])
        lp = witness.log_probs(np.frombuffer(pcm, dtype=np.int16), audio.RATE)
        slot = next(iter(r["truth"]))
        truth = r["truth"][slot]
        if r["kind"] == "digits":
            p = await agent(cache, pcm, r["audio_sha"])
            if p is None:
                digit_tally["agent_failed"] += 1
                continue
            ev = assemble(r["audio_sha"], p.values, hyps, absent, witness, lp, 0.0)
            row = Row(r["clip_id"], r["speaker"], r["condition"], r["truth"], p.response_ms or 0.0, ev)
            # Clips are collected one after another, so a slow API here says nothing about a live call's deadline.
            o = guard(row, policy.model_copy(update={"deadline_ms": 60_000.0}))
            alone_wrong = dict(p.values) != r["truth"]
            digit_tally["n"] += 1
            digit_tally["alone_wrong"] += alone_wrong
            digit_tally["guard_wrong"] += o.executed and o.wrong
            digit_tally["guard_asked"] += not o.executed
            clips.append({"clip_id": r["clip_id"], "truth": r["truth"], "agent": p.values, "guard_executed": o.executed, "guard_wrong": o.wrong})  # fmt: skip
            continue
        asked = Asked(slot=r["asked"]["slot"], options=tuple(r["asked"]["options"]))
        held = next(o for o in asked.options if o != truth)
        ev = assemble(r["audio_sha"], {slot: held}, hyps, absent, None, None)
        d = decide(resolve_answer(ev, answer_policy, asked), answer_policy)
        got = d.execute.get(slot) if d.verdict == Verdict.PASS else None
        outcome = "unresolved" if got is None else "right" if got == truth else "wrong"
        answer_tally["n"] += 1
        answer_tally[outcome] += 1
        clips.append({"clip_id": r["clip_id"], "truth": r["truth"], "outcome": outcome, "heard": {h.source: h.text for h in ev.hypotheses}})  # fmt: skip
    result = {"policy": policy.hash, "speakers": len({r["speaker"] for r in rows}), "digits": dict(digit_tally), "answers": dict(answer_tally), "clips": clips}  # fmt: skip
    (ROOT / args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "clips"}))


if __name__ == "__main__":
    asyncio.run(main())
