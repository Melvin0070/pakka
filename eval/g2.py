"""G2: can the acoustic witness tell the value that was said from a confusable one?

For every g0 clip and slot, the true value is paired with values the base arms actually produced
(g0/results.json) and with one-step confusions (29/39/49/59, 17/70, saat/aath, sava/saadhe/paune,
one changed phone digit). A pair is won when the true value has the higher log-likelihood.

Usage: uv run python eval/g2.py [--no-timing]
Caveat: the clips are synthetic speech reading romanised Hindi, and a few are mispronounced; the
failure list is printed so each can be judged by ear.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import wave
from collections import defaultdict

import numpy as np

from pramaan.render import renderings
from pramaan.witness import Witness

ROOT = pathlib.Path(__file__).resolve().parent.parent
G0 = ROOT / "g0"

# What each prompt says, in Devanagari, with the spoken form of every slot marked.
SENTENCES = {
    "a01": "अगले {weekday:मंगलवार} को {amount_rupees:पौने तीन हज़ार} रुपये दे दूँगा",
    "a02": "{amount_rupees:सवा दो लाख} का पेमेंट {day_of_month:पच्चीस} तारीख को हो जाएगा",
    "a03": "अभी {amount_rupees:ढाई हज़ार} भेज रहा हूँ बाकी {weekday:शुक्रवार} को",
    "a04": "{amount_rupees:डेढ़ लाख} रुपये {day_of_month:इक्कीस} तारीख तक पक्का",
    "a05": "{amount_rupees:साढ़े सात सौ} रुपये सीओडी है कैश रेडी रखना",
    "a06": "टोटल {amount_rupees:पचपन सौ} बनता है {weekday:सोमवार} को ट्रांसफर करूँगा",
    "a07": "{amount_rupees:उन्नीस हज़ार पाँच सौ} का ईएमआई है {day_of_month:तीन} तारीख को कटेगा",
    "a08": "{amount_rupees:उनतालीस हज़ार} रुपये {weekday:बुधवार} को दे दूँगा",
    "a09": "{amount_rupees:उनसठ हज़ार} का चेक {weekday:गुरुवार} को मिलेगा",
    "a10": "आई विल पे {amount_rupees:फिफ्टीन थाउज़ेंड} ऑन द फिफ्टीन्थ",
    "a11": "{amount_rupees:फिफ्टी थाउज़ेंड} का पेमेंट {day_of_month:सत्रह} तारीख को आएगा",
    "a12": "{amount_rupees:सत्रह हज़ार} रुपये {weekday:शनिवार} तक भेज दूँगा",
    "a13": "{amount_rupees:सत्तर हज़ार} का बैलेंस है {day_of_month:सत्ताईस} तारीख को क्लियर",
    "a14": "{amount_rupees:साढ़े बारह हज़ार} का बिल है सर",
    "a15": "{amount_rupees:पौने दो सौ} रुपये डिलीवरी चार्ज लगेगा",
    "a16": "{amount_rupees:सवा तीन सौ} का रिचार्ज कर देना {weekday:रविवार} से पहले",
    "a17": "{amount_rupees:एक लाख बीस हज़ार} {day_of_month:उनतीस} तारीख को दूँगा",
    "a18": "{amount_rupees:पचहत्तर सौ} रुपये एडवांस बाकी {weekday:मंगलवार} को",
    "a19": "{amount_rupees:तीन हज़ार तीन सौ तीस} रुपये का ऑर्डर है",
    "a20": "{amount_rupees:चौरानवे हज़ार} का लोन अमाउंट है {day_of_month:उन्नीस} तारीख को ड्यू",
    "a21": "{amount_rupees:नौ हज़ार नौ सौ निन्यानवे} का फ़ोन है ईएमआई पे",
    "a22": "{amount_rupees:थर्टीन हंड्रेड} रुपीज़ आई विल सेंड इट ऑन द थर्टीथ",
    "a23": "{amount_rupees:ढाई लाख} का डाउन पेमेंट {weekday:बुधवार} को करेंगे",
    "a24": "{amount_rupees:छह हज़ार छह सौ साठ} रुपये {day_of_month:छब्बीस} तारीख को",
    "p01": "मेरा नंबर नोट करो {phone:}",
    "p02": "इस नंबर पे कॉल करना {phone:}",
    "p03": "कॉलबैक नंबर है {phone:}",
    "p04": "{phone:} पे फ़ोन करो {amount_rupees:साढ़े चार हज़ार} के बारे में",
    "p05": "माय नंबर इज़ {phone:}",
    "p06": "{phone:} पे {weekday:शुक्रवार} को कॉल करना",
}
MARK = re.compile(r"\{(\w+):([^}]*)\}")

_EN_ONES = "ज़ीरो वन टू थ्री फ़ोर फ़ाइव सिक्स सेवन एट नाइन टेन इलेवन ट्वेल्व थर्टीन फोर्टीन फिफ्टीन सिक्सटीन सेवेंटीन एटीन नाइनटीन".split()
_EN_TENS = "_ _ ट्वेंटी थर्टी फोर्टी फिफ्टी सिक्सटी सेवेंटी एटी नाइंटी".split()


def english_amount(n: int) -> list[str]:
    """English number words as a Hindi model spells them, as this gate was run before render.py had them."""

    def below_100(k: int) -> str:
        return _EN_ONES[k] if k < 20 else (_EN_TENS[k // 10] + (f" {_EN_ONES[k % 10]}" if k % 10 else ""))

    def below_1000(k: int) -> str:
        h, r = divmod(k, 100)
        return " ".join(x for x in (f"{_EN_ONES[h]} हंड्रेड" if h else "", below_100(r) if r else "") if x)

    if not 0 < n < 1_000_000:
        return []
    th, r = divmod(n, 1000)
    forms = [" ".join(x for x in (f"{below_1000(th)} थाउज़ेंड" if th else "", below_1000(r) if r else "") if x)]
    if n % 100 == 0 and n % 1000 and n < 10000:
        forms.append(f"{below_100(n // 100)} हंड्रेड")
    return forms


def _group_swaps(g: int) -> list[int]:
    out = []
    if g % 10 == 9 and g >= 19:
        out += [g - 10, g + 10]
    if 13 <= g <= 19:
        out.append((g - 10) * 10)
    if g % 10 == 0 and 30 <= g <= 90:
        out.append(g // 10 + 10)
    out += {7: [8, 60], 8: [7], 60: [7, 70], 70: [60], 2: [3], 3: [2]}.get(g, [])
    return [x for x in out if 0 < x < 100]


def amount_neighbours(n: int) -> list[int]:
    out: list[int] = []
    for unit in (100_000, 1000, 100, 1):  # swap one two-digit group for a confusable one
        g = n // unit % 100
        out += [n + (x - g) * unit for x in _group_swaps(g)]
    for unit in (100_000, 1000, 100):  # sava / saadhe / paune and the whole number either side
        if n >= unit and n * 4 % unit == 0 and n * 4 // unit % 4:
            out += [n + d * unit // 4 for d in (-2, -1, 1, 2)]
    return [x for x in dict.fromkeys(out) if x > 0 and x != n][:5]


def neighbours(slot: str, truth):
    if slot == "amount_rupees":
        return amount_neighbours(truth)
    if slot == "day_of_month":
        return [
            d
            for d in (truth - 10, truth + 10, {7: 8, 8: 7}.get(truth % 10, 0) + truth - truth % 10)
            if 1 <= d <= 31 and d != truth
        ]
    if slot == "weekday":
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        i = days.index(truth)
        return [days[(i + 1) % 7], days[(i + 4) % 7]]
    swap = {
        "7": "8",
        "8": "7",
        "6": "7",
        "1": "9",
        "9": "5",
        "5": "9",
        "2": "3",
        "3": "2",
        "4": "1",
        "0": "2",
    }
    return [truth[:i] + swap[truth[i]] + truth[i + 1 :] for i in (2, 5, 8)]


def forms(slot: str, value, pid: str) -> list[str]:
    out = renderings(slot, value)
    if slot == "amount_rupees" and pid in ("a10", "a11", "a22"):
        out = out + english_amount(int(value))
    return out


def context_for(pid: str, slot: str) -> tuple[str, str]:
    left, right = "", ""
    seen = False
    pos = 0
    text = SENTENCES[pid]
    for m in MARK.finditer(text):
        chunk = text[pos : m.start()]
        if m.group(1) == slot and not seen:
            left += chunk
            seen = True
        elif seen:
            right += chunk + m.group(2)
        else:
            left += chunk + m.group(2)
        pos = m.end()
    right += text[pos:]
    return " ".join(left.split()), " ".join(right.split())


def load(path: pathlib.Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()


def valid(slot: str, v) -> bool:
    if slot == "phone":
        return isinstance(v, str) and v.isdigit() and len(v) >= 8
    if slot == "weekday":
        return isinstance(v, str)
    return isinstance(v, int) and 0 < v < 1_000_000_000 and (slot != "day_of_month" or v <= 31)


def main() -> None:
    prompts = {p["id"]: p["truth"] for p in json.loads((G0 / "prompts.json").read_text())}
    results = json.loads((G0 / "results.json").read_text())
    heard: dict[tuple[str, str], set] = defaultdict(set)  # wrong values any base arm produced
    for key, out in results.items():
        pid = key.split("|")[0].split("_")[1]
        for slot, truth in prompts[pid].items():
            v = out.get(slot)
            if slot in ("amount_rupees", "day_of_month") and isinstance(v, str) and v.isdigit():
                v = int(v)
            if v is not None and v != truth and valid(slot, v):
                heard[pid, slot].add(v)

    witness = Witness()
    modes = {"context": dict(filler="max"), "star-max": dict(filler="max"), "star-free": dict(filler="free")}
    tally: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    top: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    failures, margins, score_ms = [], defaultdict(list), []
    for clip in sorted((G0 / "clips").glob("*.wav")):
        speaker, pid, cond = clip.stem.split("_")
        lp = witness.log_probs(*load(clip))
        for slot, truth in prompts[pid].items():
            if slot == "day_of_month" and pid in ("a10", "a22"):
                continue  # English ordinals: no rendering yet
            alts = list(dict.fromkeys([*sorted(heard[pid, slot], key=str), *neighbours(slot, truth)]))
            cands = {str(v): forms(slot, v, pid) for v in [truth, *alts]}
            for mode, kw in modes.items():
                ws = witness.score_slot(
                    lp, slot, cands, context_for(pid, slot) if mode == "context" else None, **kw
                )
                score_ms.append(ws.latency_ms / len(cands))
                t = ws.loglik[str(truth)]
                best = max(ws.loglik, key=lambda k: ws.loglik[k])
                top[mode, cond][0] += best == str(truth)
                top[mode, cond][1] += 1
                for v in alts:
                    won = t > ws.loglik[str(v)]
                    keys = [(mode, cond, slot), (mode, cond, "all")]
                    if v in heard[pid, slot]:
                        keys.append(
                            (mode, cond, "base_arm_error")
                        )  # the pairs that matter: a real model said this
                    for k in keys:
                        tally[k][0] += won
                        tally[k][1] += 1
                    margins[mode, cond].append(t - ws.loglik[str(v)])
                    if not won and mode == "context":
                        failures.append(
                            {
                                "clip": clip.stem,
                                "slot": slot,
                                "truth": truth,
                                "preferred": v,
                                "llr": round(t - ws.loglik[str(v)], 2),
                                "greedy": witness.greedy(lp),
                                "from_base_arm": v in heard[pid, slot],
                            }
                        )

    slots = ["all", "base_arm_error", "amount_rupees", "day_of_month", "weekday", "phone"]
    print(
        f"\nPairwise accuracy (true value scores higher), {len(list((G0 / 'clips').glob('*_phone.wav')))} clips per condition"
    )
    print(
        f"{'mode':10} {'cond':6} "
        + " ".join(f"{s[:13]:>15}" for s in slots)
        + f" {'truth is top':>14} {'median LLR':>11}"
    )
    table = {}
    for mode in modes:
        for cond in ("phone", "clean"):
            cells = []
            for s in slots:
                w, n = tally[mode, cond, s]
                cells.append(f"{w}/{n} {100 * w / max(n, 1):3.0f}%".rjust(15))
                table[f"{mode}|{cond}|{s}"] = {"won": w, "pairs": n}
            tw, tn = top[mode, cond]
            table[f"{mode}|{cond}|truth_top"] = {"won": tw, "slots": tn}
            print(
                f"{mode:10} {cond:6} "
                + " ".join(cells)
                + f" {f'{tw}/{tn}':>14} {np.median(margins[mode, cond]):11.1f}"
            )

    print(f"\nContext-mode failures ({len(failures)}):")
    for f in failures:
        print(
            f"  {f['clip']:20} {f['slot']:14} said {f['truth']}, witness prefers {f['preferred']} by {-f['llr']:.2f} nats"
            f"{' (a base arm also heard this)' if f['from_base_arm'] else ''}\n      greedy: {f['greedy']}"
        )

    timing: dict[str, object] = {"score_ms_per_candidate_mean": round(float(np.mean(score_ms)), 2)}
    if "--no-timing" not in sys.argv:
        clips = sorted((G0 / "clips").glob("*_phone.wav"))[:20]
        for int8 in (False, True):
            w = Witness(cache_dir=None, int8=int8)
            w.log_probs(*load(clips[0]))  # load and warm up
            times, secs = [], []
            for c in clips:
                pcm, sr = load(c)
                t0 = time.perf_counter()
                w.log_probs(pcm, sr)
                times.append((time.perf_counter() - t0) * 1000)
                secs.append(len(pcm) / sr)
            timing[w.variant] = {
                "ms_per_clip_mean": round(float(np.mean(times)), 1),
                "ms_per_clip_max": round(max(times), 1),
                "audio_s_mean": round(float(np.mean(secs)), 2),
            }
    print("\nTiming:", json.dumps(timing))
    w, n = tally["context", "phone", "all"]
    print(
        f"\nG2 (rule: at least 85% of confusable pairs on phone-grade audio): {w}/{n} = {100 * w / n:.1f}% -> {'PASS' if w >= 0.85 * n else 'FAIL'}"
    )
    out = ROOT / "results" / "g2.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "note": "synthetic speech (2 TTS voices x 30 prompts); phone = 8 kHz mu-law round trip",
                "accuracy": table,
                "failures_context": failures,
                "timing": timing,
            },
            indent=1,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
