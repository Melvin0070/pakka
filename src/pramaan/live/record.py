"""Record human callers reading the evaluation prompts: the locked test set the synthetic voices stand in for.

Each speaker gets a fixed slice of data/prompts.jsonl. The browser uploads 24 kHz PCM16 mono; the clip is
kept raw and also passed through the same phone channel as the synthetic set, and only the phone version
enters data/human/manifest.jsonl.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import wave
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Request

from .. import audio

ROOT = Path(__file__).resolve().parents[3]
HUMAN = ROOT / "data" / "human"
MANIFEST = HUMAN / "manifest.jsonl"
PER_SPEAKER = 15
ORDER_SEED = 20261121
MAX_BYTES = 3_000_000  # about 60 s at 24 kHz PCM16
_SPEAKER = re.compile(r"[a-z0-9]{2,12}")

router = APIRouter(prefix="/api/record")


def _prompts() -> list[dict[str, Any]]:
    rows = [json.loads(x) for x in (ROOT / "data" / "prompts.jsonl").read_text().splitlines() if x.strip()]
    rows.sort(key=lambda p: p["id"])
    random.Random(ORDER_SEED).shuffle(rows)
    return rows


def _manifest() -> list[dict[str, Any]]:
    if not MANIFEST.exists():
        return []
    return [json.loads(x) for x in MANIFEST.read_text().splitlines() if x.strip()]


def _check(speaker: str) -> None:
    synthetic = json.loads((ROOT / "data" / "splits.json").read_text())
    if not _SPEAKER.fullmatch(speaker) or speaker in synthetic["tune"] + synthetic["test"]:
        raise HTTPException(422, "speaker code: 2-12 lowercase letters or digits, not a synthetic voice name")


def _assigned(speaker: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Slices follow arrival order, so eight speakers cover all 120 prompts once.
    order = list(dict.fromkeys(r["speaker"] for r in rows))
    i = order.index(speaker) if speaker in order else len(order)
    prompts = _prompts()
    return [prompts[(i * PER_SPEAKER + j) % len(prompts)] for j in range(PER_SPEAKER)]


@router.get("/prompts")
def prompts(speaker: str) -> dict[str, Any]:
    _check(speaker)
    rows = _manifest()
    done = {r["prompt_id"] for r in rows if r["speaker"] == speaker}
    return {
        "speaker": speaker,
        "speakers": len({r["speaker"] for r in rows}),
        "clips": len(rows),
        "prompts": [
            {"id": p["id"], "say": p["say"], "lang": p["lang"], "done": p["id"] in done}
            for p in _assigned(speaker, rows)
        ],
    }


@router.post("/{speaker}/{prompt_id}")
async def save(speaker: str, prompt_id: str, request: Request) -> dict[str, Any]:
    _check(speaker)
    rows = _manifest()
    prompt = next((p for p in _assigned(speaker, rows) if p["id"] == prompt_id), None)
    if prompt is None:
        raise HTTPException(404, "prompt not assigned to this speaker")
    body = await request.body()
    if len(body) > MAX_BYTES:
        raise HTTPException(413, "clip too long")
    try:
        with wave.open(io.BytesIO(body)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError("need PCM16 mono")
            pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    except (wave.Error, ValueError, EOFError) as e:
        raise HTTPException(422, f"bad wav: {e}") from e
    pcm = audio.resample(pcm, rate, audio.RATE)
    seconds = len(pcm) / 2 / audio.RATE
    peak = float(np.abs(np.frombuffer(pcm, dtype="<i2").astype(np.int32)).max()) / 32768 if pcm else 0.0
    if seconds < 1.0:
        raise HTTPException(422, "clip shorter than one second")
    if peak < 0.05:
        raise HTTPException(422, "almost silent: check the microphone")

    raw = HUMAN / "clips" / speaker / f"{prompt_id}_raw.wav"
    phone = raw.with_name(f"{prompt_id}_phone.wav")
    audio.write_wav(raw, pcm)
    audio.phone_amr(raw, phone)
    row = {
        "clip_id": f"{speaker}_{prompt_id}_phone",
        "speaker": speaker,
        "prompt_id": prompt_id,
        "condition": "phone",
        "path": os.path.relpath(phone, ROOT),
        "audio_sha": audio.sha(audio.read_pcm24k(phone)),
        "truth": prompt["truth"],
    }
    rows = [r for r in rows if r["clip_id"] != row["clip_id"]] + [row]
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(MANIFEST)
    return {
        "clip_id": row["clip_id"],
        "seconds": round(seconds, 1),
        "peak": round(peak, 2),
        "clipped": peak > 0.98,
    }
