"""G0: same clips through (A) bare gpt-realtime-2.1 tool call and (B) gpt-transcribe + hints + typed extraction.
Usage: python g0/run.py [--only phone|clean] [--speaker name]"""
import asyncio, base64, json, os, sys, wave
import websockets
from openai import OpenAI
from common import CLIPS, FIELDS, HERE, INSTRUCTIONS, PROMPTS, TOOL, norm

client = OpenAI()
TRUTH = {p["id"]: p["truth"] for p in PROMPTS}
CACHE = HERE / "results.json"
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}


async def arm_a(pcm):
    url = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1"
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                                  max_size=None) as ws:
        await ws.send(json.dumps({"type": "session.update", "session": {
            "type": "realtime", "output_modalities": ["text"], "instructions": INSTRUCTIONS,
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None}},
            "tools": [TOOL], "tool_choice": "required"}}))
        await ws.send(json.dumps({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_audio", "audio": base64.b64encode(pcm).decode()}]}}))
        await ws.send(json.dumps({"type": "response.create"}))
        async for raw in ws:
            ev = json.loads(raw)
            if ev["type"] == "error":
                return {"_error": ev["error"].get("message", str(ev["error"]))}
            if ev["type"] == "response.done":
                for item in ev["response"].get("output", []):
                    if item.get("type") == "function_call":
                        return json.loads(item["arguments"])
                return {"_error": f"no tool call (status {ev['response'].get('status')})"}


def arm_b(path):
    with open(path, "rb") as f:
        tr = client.audio.transcriptions.create(
            model="gpt-transcribe", file=f,
            prompt="A phone call in India about a payment amount in rupees, a date, or a callback phone number.",
            extra_body={"languages": ["hi", "en"]})
    r = client.responses.create(
        model="gpt-6.2-sol", instructions=INSTRUCTIONS + " Work only from the transcript given.",
        input=tr.text, tools=[TOOL], tool_choice="required")
    for item in r.output:
        if item.type == "function_call":
            return {**json.loads(item.arguments), "_transcript": tr.text}
    return {"_error": "no tool call", "_transcript": tr.text}


def pcm_of(path):
    with wave.open(str(path)) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return w.readframes(w.getnframes())


def wrong_fields(pid, out):
    return [f for f, t in TRUTH[pid].items() if norm(f, out.get(f)) != norm(f, t)]


only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
speaker = sys.argv[sys.argv.index("--speaker") + 1] if "--speaker" in sys.argv else None
clips = sorted(c for c in CLIPS.glob("*.wav") if (not only or c.stem.endswith(only))
               and (not speaker or c.stem.startswith(speaker + "_")))
if not clips:
    sys.exit("No clips in g0/clips. Run: python g0/record.py")
for c in clips:
    for arm in ("A", "B"):
        key = f"{c.stem}|{arm}"
        if key not in cache:
            try:
                cache[key] = asyncio.run(arm_a(pcm_of(c))) if arm == "A" else arm_b(c)
            except Exception as e:
                cache[key] = {"_error": f"{type(e).__name__}: {e}"}
            CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False))

print(f"\n{'clip':22} {'truth':34} A  B   detail")
tot = {}
for c in clips:
    pid, cond = c.stem.split("_")[1], c.stem.split("_")[2]
    row = []
    for arm in ("A", "B"):
        out = cache[f"{c.stem}|{arm}"]
        bad = ["ERR"] if "_error" in out else wrong_fields(pid, out)
        t = tot.setdefault((cond, arm), [0, 0, 0])
        t[0] += 1; t[1] += bool(bad); t[2] += "_error" in out
        row.append((bad, out))
    detail = "; ".join(f"{arm}:{f}={out.get(f) if f != 'ERR' else out['_error'][:60]}"
                       for arm, (bad, out) in zip("AB", row) for f in bad)
    print(f"{c.stem:22} {json.dumps(TRUTH[pid])[:34]:34} {'x' if row[0][0] else '.'}  {'x' if row[1][0] else '.'}   {detail}")

print("\nTurns with at least one wrong value:")
for (cond, arm), (n, bad, err) in sorted(tot.items()):
    print(f"  {cond:6} arm {arm}: {bad}/{n} wrong" + (f"  ({err} were errors, not mishearings)" if err else ""))
ph = {arm: tot.get(("phone", arm), [0, 0, 0]) for arm in "AB"}
if ph["A"][0] >= 25:
    a, b = ph["A"][1] - ph["A"][2], ph["B"][1] - ph["B"][2]
    print(f"\nG0 on phone-grade clips: A wrong {a}, B wrong {b}  ->  {'GO' if a >= 3 and b >= 2 else 'NO-GO as specified'} (rule: A >= 3 and B >= 2 of 30)")
