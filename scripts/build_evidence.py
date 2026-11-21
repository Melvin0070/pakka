"""Build data/evidence.jsonl: one fully typed Evidence per collected clip, with every source present.

This is the only step that needs the acoustic model. `make eval` replays the file with no model, key or
network, applying each arm's deadline by dropping sources whose recorded latency missed it.
Usage: uv run python scripts/build_evidence.py [--conditions phone,noisy] [--manifest PATH --out PATH]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

from pramaan import audio
from pramaan.cache import CacheMiss
from pramaan.evidence import assemble
from pramaan.sources import realtime_agent
from pramaan.sources.registry import gather
from pramaan.witness import Witness

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    conditions = {"phone", "noisy"}
    if "--conditions" in sys.argv:
        conditions = set(sys.argv[sys.argv.index("--conditions") + 1].split(","))

    def arg(flag: str, default: str) -> Path:
        return ROOT / (sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default)

    out = arg("--out", "data/evidence.jsonl")
    manifest = [json.loads(x) for x in arg("--manifest", "data/manifest.jsonl").read_text().splitlines() if x]
    witness = Witness()
    rows, skipped = [], 0
    for i, m in enumerate(m for m in manifest if m["condition"] in conditions):
        pcm = audio.read_pcm24k(ROOT / m["path"])
        try:
            proposal = await realtime_agent.propose(pcm, m["audio_sha"])
            hyps, absent = await gather(pcm, None, audio_sha=m["audio_sha"])
        except (CacheMiss, ExceptionGroup):
            skipped += 1
            continue
        t0 = time.perf_counter()
        lp = witness.log_probs(np.frombuffer(pcm, dtype=np.int16), audio.RATE)
        ev = assemble(
            m["audio_sha"], proposal.values if proposal else {}, hyps, absent, witness, lp,
            (time.perf_counter() - t0) * 1000,
        )  # fmt: skip
        rows.append(
            {
                **{k: m[k] for k in ("clip_id", "speaker", "prompt_id", "condition", "truth")},
                "duration_s": len(pcm) / 2 / audio.RATE,
                "agent_failed": proposal is None,
                "agent_response_ms": proposal.response_ms if proposal else None,
                "evidence": ev.model_dump(mode="json"),
            }
        )
        if i % 50 == 0:
            print(f"{i} clips", flush=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows))
    print(f"wrote {len(rows)} rows to {out} ({skipped} skipped: not collected)")


if __name__ == "__main__":
    asyncio.run(main())
