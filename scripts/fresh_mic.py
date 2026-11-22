import asyncio
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import websockets

OUT = Path(sys.argv[1])
PORT = sys.argv[2]
CLIPS = OUT / "fresh_clips"
CLIPS.mkdir(parents=True, exist_ok=True)
RATE = 24000
FRAME = RATE * 2 // 10

PROMPTS = [
    ("बारह हज़ार पाँच सौ रुपये शुक्रवार को दे दूँगा।", {"amount_rupees": 12500, "weekday": "friday"}),
    ("साढ़े चार हज़ार रुपये सत्रह तारीख को भेजूँगा।", {"amount_rupees": 4500, "day_of_month": 17}),
    ("पौने दो लाख का payment सोमवार को होगा।", {"amount_rupees": 175000, "weekday": "monday"}),
    ("मेरा नंबर है नौ चार आठ तीन, सात दो, छह एक पाँच शून्य।", {"phone": "9483726150"}),
    ("ढाई हज़ार रुपये मंगलवार को दूँगा।", {"amount_rupees": 2500, "weekday": "tuesday"}),
    ("उनचास हज़ार रुपये इक्कीस तारीख तक दे दूँगा।", {"amount_rupees": 49000, "day_of_month": 21}),
    ("सवा तीन लाख रुपये बुधवार को ट्रांसफर करूँगा।", {"amount_rupees": 325000, "weekday": "wednesday"}),
    ("छत्तीस सौ रुपये पच्चीस तारीख को दूँगा।", {"amount_rupees": 3600, "day_of_month": 25}),
    ("मेरा नंबर लिखो आठ दो, छह छह, सात एक, नौ तीन, पाँच चार।", {"phone": "8266719354"}),
    ("डेढ़ हज़ार रुपये रविवार को भेज दूँगा।", {"amount_rupees": 1500, "weekday": "sunday"}),
    ("तिरेसठ हज़ार रुपये शनिवार को मिलेंगे।", {"amount_rupees": 63000, "weekday": "saturday"}),
    ("अठहत्तर सौ रुपये दस तारीख को दे दूँगा।", {"amount_rupees": 7800, "day_of_month": 10}),
]
SLOTS = ("amount_rupees", "weekday", "day_of_month", "phone")


def pcm(i: int, text: str) -> bytes:
    path = CLIPS / f"f{i:02d}.wav"
    subprocess.run(
        ["say", "-v", "Lekha", "-o", str(path), "--file-format=WAVE", "--data-format=LEI16@24000", text],
        check=True,
    )
    with wave.open(str(path)) as w:
        return w.readframes(w.getnframes())


def vals(e):
    v = e.get("values") or {}
    return {k: v[k] for k in SLOTS if v.get(k) is not None}


async def call(audio: bytes) -> list[dict]:
    events: list[dict] = []
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws?left=independent", max_size=None) as ws:

        async def reader():
            async for raw in ws:
                e = json.loads(raw)
                if e.get("type") not in ("agent.audio", "caller.audio"):
                    events.append(e)

        task = asyncio.create_task(reader())
        while not any(e["type"] == "session.ready" for e in events):
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        stream = audio + b"\0" * (RATE * 2 * 16)
        next_at = time.monotonic()
        spoken_end = len(audio)
        for pos in range(0, len(stream), FRAME):
            await ws.send(stream[pos : pos + FRAME])
            next_at += 0.1
            await asyncio.sleep(max(next_at - time.monotonic(), 0))
            kinds = {e["type"] for e in events}
            settled = "left.committed" in kinds and bool(
                kinds & {"right.committed", "right.escalated", "question.asked"}
            )
            if pos > spoken_end and settled:
                await asyncio.sleep(1.0)
                break
        task.cancel()
    return events


async def main() -> None:
    rows = []
    for i, (text, truth) in enumerate(PROMPTS):
        events = await call(pcm(i, text))
        left = [vals(e) for e in events if e["type"] == "left.committed"]
        right = [vals(e) for e in events if e["type"] == "right.committed"]
        kinds = sorted({e["type"] for e in events if e["type"].startswith("right.")})
        a, p = left[-1] if left else None, right[-1] if right else None
        rows.append(
            {"i": i, "text": text, "truth": truth, "alone": a, "pramaan": p, "kinds": kinds, "events": events}
        )
        print(
            i,
            "truth",
            truth,
            "| alone",
            a,
            "OK" if a == truth else "WRONG",
            "| pramaan",
            p,
            "OK" if p == truth else ("NO-COMMIT" if p is None else "WRONG"),
            kinds,
            flush=True,
        )
    (OUT / "fresh_mic.json").write_text(json.dumps(rows, ensure_ascii=False))
    n = len(rows)
    wrong_a = sum(r["alone"] != r["truth"] for r in rows)
    right_p = sum(r["pramaan"] == r["truth"] for r in rows)
    wrong_p = sum(r["pramaan"] is not None and r["pramaan"] != r["truth"] for r in rows)
    print(
        f"\nalone not right {wrong_a}/{n}; pramaan right {right_p}/{n}, wrong committed {wrong_p}/{n}, no commit {n - right_p - wrong_p}/{n}"
    )


asyncio.run(main())
