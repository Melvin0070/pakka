"""Write data/human/prompts.jsonl: 150 prompts for ten people, with values absent from every synthetic batch.

Never redrawn once written, because recordings are tied to these ids.
Usage: uv run python scripts/gen_human_prompts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_fresh  # noqa: E402

SEED = 20261130
N = 150


def main() -> None:
    path = ROOT / "data" / "human" / "prompts.jsonl"
    if path.exists():
        sys.exit(f"{path} already exists")
    gen_fresh.N = N
    rows = gen_fresh.prompts(SEED, "r")
    path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in rows))
    print(
        f"{len(rows)} prompts, {sum(p['lang'] == 'en' for p in rows)} English, {sum(p['hard'] for p in rows)} confusable"
    )


if __name__ == "__main__":
    main()
