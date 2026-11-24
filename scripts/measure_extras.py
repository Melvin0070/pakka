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

from eval.common import DELTA, ROOT, Row, guard
from pakka import audio
from pakka.cache import Cache
from pakka.decide import decide, resolve_answer
from pakka.evidence import assemble
from pakka.gate import cp_upper
from pakka.live.tooling import LEFT_INSTRUCTIONS, TOOL
from pakka.pipeline import load_policy
from pakka.sources import realtime_agent as ra
from pakka.sources.base import PermanentError, with_retries
from pakka.sources.registry import gather
from pakka.types import Asked, Verdict
from pakka.witness import Witness

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
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()
    rows = [json.loads(x) for x in (ROOT / args.manifest).read_text().splitlines() if x.strip()]
    policy, witness = load_policy(), Witness()
    answer_policy = policy.model_copy(update={"require_witness": False, "accept_threshold": 0.0})
    cache = Cache(os.environ.get("PAKKA_EXTRAS_CACHE") or ROOT / "data" / "cache.extras.sqlite")
    sem = asyncio.Semaphore(args.concurrency)

    async def one(r: dict) -> dict:
        async with sem:
            pcm = audio.read_pcm24k(Path(ROOT / r["path"]))
            hyps, absent = await gather(pcm, None, audio_sha=r["audio_sha"])
            slot = next(iter(r["truth"]))
            truth = r["truth"][slot]
            base = {"clip_id": r["clip_id"], "kind": r["kind"], "slot": slot, "truth": r["truth"]}
            if r["kind"] == "digits":
                p = await agent(cache, pcm, r["audio_sha"])
                if p is None:
                    return {**base, "agent_failed": True}
                lp = await asyncio.to_thread(
                    witness.log_probs, np.frombuffer(pcm, dtype=np.int16), audio.RATE
                )
                ev = await asyncio.to_thread(
                    assemble, r["audio_sha"], p.values, hyps, absent, witness, lp, 0.0
                )
                row = Row(r["clip_id"], r["speaker"], r["condition"], r["truth"], p.response_ms or 0.0, ev)
                # Clips are collected in bulk, so a slow API here says nothing about a live call's deadline.
                o = guard(row, policy.model_copy(update={"deadline_ms": 60_000.0}))
                return {**base, "agent": p.values, "agent_wrong": dict(p.values) != r["truth"], "guard_executed": o.executed, "guard_wrong": o.wrong}  # fmt: skip
            asked = Asked(slot=r["asked"]["slot"], options=tuple(r["asked"]["options"]))
            held = next(o for o in asked.options if o != truth)
            ev = assemble(r["audio_sha"], {slot: held}, hyps, absent, None, None)
            d = decide(resolve_answer(ev, answer_policy, asked), answer_policy)
            got = d.execute.get(slot) if d.verdict == Verdict.PASS else None
            outcome = "unresolved" if got is None else "right" if got == truth else "wrong"
            return {**base, "outcome": outcome, "heard": {h.source: h.text for h in ev.hypotheses}}

    clips = await asyncio.gather(*(one(r) for r in rows))
    digit_tally, answer_tally = Counter(), Counter()
    by_slot: dict[str, Counter[str]] = {}
    for c in clips:
        if c["kind"] != "digits":
            answer_tally["n"] += 1
            answer_tally[c["outcome"]] += 1
            continue
        if c.get("agent_failed"):
            digit_tally["agent_failed"] += 1
            continue
        for t in (digit_tally, by_slot.setdefault(c["slot"], Counter())):
            t["n"] += 1
            t["alone_wrong"] += c["agent_wrong"]
            t["guard_wrong"] += c["guard_executed"] and c["guard_wrong"]
            t["guard_asked"] += not c["guard_executed"]
            t["guard_asked_wrong"] += not c["guard_executed"] and c["agent_wrong"]
    accepted = digit_tally["n"] - digit_tally["guard_asked"]
    result = {
        "policy": policy.hash,
        "speakers": len({r["speaker"] for r in rows}),
        "digits": dict(digit_tally),
        "digits_by_slot": {s: dict(t) for s, t in sorted(by_slot.items())},
        "digits_upper_bound": round(cp_upper(digit_tally["guard_wrong"], accepted, DELTA), 4) if accepted else None,
        "answers": dict(answer_tally),
        "clips": clips,
    }  # fmt: skip
    (ROOT / args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "clips"}))


if __name__ == "__main__":
    asyncio.run(main())
