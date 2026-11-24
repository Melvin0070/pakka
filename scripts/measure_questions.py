"""Measure what happens after Pakka asks: replay each asked test action through the live server, followed
by a spoken answer, and record what is finally committed.

The answers are synthetic and cooperative (the same voice states the true value of the slot asked about, over
the phone channel), so this measures the mechanism, not how real callers respond to a question.
Needs a running server (make serve) and OPENAI_API_KEY. Writes results/questions.json.
Usage: uv run python scripts/measure_questions.py [--url ws://127.0.0.1:8765] [--concurrency 4] [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import websockets
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.common import EVIDENCE, load, split, within  # noqa: E402
from pakka import audio  # noqa: E402
from pakka.decide import decide  # noqa: E402
from pakka.lexicon import HI_0_99, HI_WEEKDAYS  # noqa: E402
from pakka.pipeline import load_policy  # noqa: E402
from pakka.render import hindi_cardinal  # noqa: E402
from pakka.types import Verdict  # noqa: E402

ANSWERS = ROOT / "data" / "clips" / "answers"
OUT = ROOT / "results" / "questions.json"


def answer_text(slot: str, value: object, lang: str) -> str:
    if lang == "en":
        if slot == "amount_rupees":
            return f"Yes, {int(str(value)):,} rupees."
        if slot == "day_of_month":
            d = int(str(value))
            suffix = "th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
            return f"Yes, the {d}{suffix}."
        if slot == "weekday":
            return f"Yes, {str(value).capitalize()}."
        return "Yes, " + " ".join(str(value)) + "."
    if slot == "amount_rupees":
        return f"जी, {hindi_cardinal(int(str(value)))} रुपये।"
    if slot == "day_of_month":
        return f"जी, {hindi_cardinal(int(str(value)))} तारीख।"
    if slot == "weekday":
        return f"जी, {HI_WEEKDAYS[str(value)][0]}।"
    words = [HI_0_99[int(d)] for d in str(value)]
    return "जी, " + " ".join(words[:5]) + ", " + " ".join(words[5:]) + "।"


async def synth(client: AsyncOpenAI, voice: str, text: str, dst: Path) -> None:
    if dst.exists():
        return
    r = await client.with_options(max_retries=5).audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text,
        instructions="This is a phone call. Answer a question briefly; say exactly the words given.",
        response_format="pcm",
    )
    raw = dst.with_name(dst.stem + "_raw.wav")
    audio.write_wav(raw, r.content)
    audio.phone_amr(raw, dst)
    raw.unlink()


FRAME = 4800  # 100 ms of 24 kHz PCM16, the size the browser microphone sends


async def run_one(
    url: str, clip: Path, answers: dict[str, Path], slot: str, timeout_s: float = 150.0
) -> dict:
    """Drive the microphone path: play the clip, then answer each question with the clip for the slot asked."""
    out: dict = {"questions": [], "outcome": "timeout", "committed": None}
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    queue.put_nowait(audio.read_pcm24k(clip))

    async def speak(ws: websockets.ClientConnection) -> None:
        while True:
            pcm = b"" if queue.empty() else queue.get_nowait()
            for i in range(0, max(len(pcm), 1), FRAME):
                await ws.send(pcm[i : i + FRAME] or b"\0" * FRAME)
                await asyncio.sleep(0.1)

    try:
        async with websockets.connect(f"{url}/ws?left=0", max_size=None) as ws:
            talker = asyncio.create_task(speak(ws))
            pending: str | None = None
            try:
                async with asyncio.timeout(timeout_s):
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        e = json.loads(raw)
                        kind = e["type"]
                        if kind == "question.asked":
                            pending = e.get("slot") or slot
                            out["questions"].append(
                                {"text": e["text"], "slot": pending, "kind": e.get("ask_kind")}
                            )
                        elif kind == "agent.said" and pending:
                            # The caller replies once the agent has finished asking.
                            await asyncio.sleep(0.8)
                            queue.put_nowait(audio.read_pcm24k(answers.get(pending, answers[slot])))
                            pending = None
                        elif kind == "right.proposed":
                            out.setdefault("proposed", []).append(e["values"])
                        elif kind == "decision":
                            out.setdefault("decisions", []).append(
                                [
                                    (
                                        x["slot"],
                                        x["proposed"],
                                        x["verdict"],
                                        x["reason"],
                                        x["supporting_families"],
                                    )
                                    for x in e["slots"]
                                ]
                            )
                        elif kind == "right.committed":
                            out["outcome"], out["committed"] = "committed", e["values"]
                            break
                        elif kind == "right.escalated":
                            out["outcome"] = "escalated"
                            break
                        elif kind == "error":
                            out.setdefault("errors", []).append(e.get("message"))
            finally:
                talker.cancel()
    except TimeoutError:
        pass
    except Exception as e:  # noqa: BLE001 - one failed call must not lose the rest of the run
        out["outcome"], out["errors"] = "failed", [repr(e)]
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--split", choices=("tune", "test"), default="test")
    args = ap.parse_args()

    policy = load_policy()
    tune, test = split(load()[0])
    if args.split == "tune":
        test = tune
    prompt_of = {r["clip_id"]: r["prompt_id"] for r in map(json.loads, EVIDENCE.read_text().splitlines())}
    lang = {
        p["id"]: p["lang"]
        for p in map(json.loads, (ROOT / "data" / "prompts.jsonl").read_text().splitlines())
    }
    asked = []
    for r in test:
        d = decide(within(r, policy.deadline_ms), policy)
        slot = d.question_slot or next((s.slot for s in d.slots if s.verdict != Verdict.PASS), None)
        if d.verdict != Verdict.PASS and slot in r.truth:
            asked.append((r, slot))
    asked = asked[: args.limit or None]
    print(f"{len(asked)} asked actions to replay")

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(args.concurrency)
    out_path = OUT if args.split == "test" else OUT.with_name("questions_tune.json")
    # Finished calls are kept across runs: a live replay is slow and a dropped connection should not lose them.
    partial = out_path.with_suffix(".partial.jsonl")
    results: list[dict] = (
        [json.loads(x) for x in partial.read_text().splitlines()] if partial.exists() else []
    )
    have = {x["clip_id"] for x in results}
    asked = [(r, s) for r, s in asked if r.clip_id not in have]

    path_of = {
        r["clip_id"]: ROOT / r["path"]
        for r in map(json.loads, (ROOT / "data" / "manifest.jsonl").read_text().splitlines())
    }

    async def one(r, slot: str) -> None:  # noqa: ANN001
        answers = {k: ANSWERS / r.speaker / f"{r.clip_id}_{k}.wav" for k in r.truth}
        async with sem:
            for k, dst in answers.items():
                await synth(client, r.speaker, answer_text(k, r.truth[k], lang[prompt_of[r.clip_id]]), dst)
            res = await run_one(args.url, path_of[r.clip_id], answers, slot)
        if res["outcome"] == "timeout" and not res.get("proposed"):
            res["outcome"] = "agent_made_no_call"
        committed = {k: v for k, v in (res["committed"] or {}).items() if v is not None}
        res.update(
            clip_id=r.clip_id, slot=slot, truth=r.truth, agent_was_wrong=dict(r.evidence.proposed) != r.truth,
            right=res["outcome"] == "committed" and committed == r.truth,
        )  # fmt: skip
        results.append(res)
        with partial.open("a") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        print(
            f"{len(results)} {res['clip_id']} {res['outcome']} right={res['right']} q={len(res['questions'])}",
            flush=True,
        )

    done = await asyncio.gather(*(one(r, s) for r, s in asked), return_exceptions=True)
    failed = [repr(e) for e in done if isinstance(e, BaseException)]
    if failed:
        sys.exit(f"\n{len(failed)} calls failed ({failed[0]}); run again to resume")
    results.sort(key=lambda x: x["clip_id"])
    n = len(results)
    tally = Counter(
        "committed_right"
        if x["right"]
        else "committed_wrong"
        if x["outcome"] == "committed"
        else x["outcome"]
        for x in results
    )
    summary = {
        "n": n,
        "policy_hash": policy.hash,
        "split": args.split,
        "answers": "synthetic, cooperative: the same voice states the true value of the slot asked, over the phone channel",
        "outcomes": dict(sorted(tally.items())),
        "committed_without_asking_live": sum(
            x["outcome"] == "committed" and not x["questions"] for x in results
        ),
        "questions_per_action_mean": round(sum(len(x["questions"]) for x in results) / n, 2) if n else 0,
        "actions": results,
    }
    out_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    print(
        "\n" + json.dumps({k: v for k, v in summary.items() if k != "actions"}, indent=1, ensure_ascii=False)
    )


if __name__ == "__main__":
    asyncio.run(main())
