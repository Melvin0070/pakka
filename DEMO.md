# Demo runbook

## Before the slot
1. `make demo` (self-check, then the server). Open http://127.0.0.1:8765 in Chrome with a headset.
2. Play "An amount the agent left out" once to warm the models.
3. Have `make demo-offline` ready in a second terminal in case the network fails.

## Two minutes
| Time | Screen | Say |
|---|---|---|
| 0:00 | Before and after | "A speech-to-speech agent goes from sound straight to action. On the same recorded calls it acted on a wrong amount, date or phone number 29.5% of the time. With Pramaan checking each action, 0.9%, with a question on 5.9% of calls." |
| 0:25 | Play "An amount the agent left out" | "Left: the model alone logs Thursday and drops the amount. Right: the same model, held for about a second, and the amount is restored from the evidence." |
| 0:50 | Play "Evidence is split, so it asks" | "Here the recognisers disagree on one digit, so the agent asks about that digit only, and commits after the answer." |
| 1:20 | Evidence | "Every decision is recorded: what each recogniser heard, when it answered, and why the action went through." |
| 1:35 | Live call, microphone | Ask a judge to say an amount and a date in Hindi or Hinglish. |
| 1:55 | Results | "Every number here is reproduced offline by `make eval`, including the baselines we did not beat on errors." |

## Which calls to trust live
Five live runs each, real models:

| Call | Model alone wrong | Pramaan right |
|---|---|---|
| An amount the agent left out | 5 of 5 | 5 of 5 |
| One digit of a phone number | 5 of 5 | 5 of 5 |
| Evidence is split, so it asks | 5 of 5 | 5 of 5 |
| A Hindi fraction, misheard | 3 of 5 | 5 of 5 |

Lead with the first and third. The model alone does not make the identical mistake each time.

## If something breaks
- Network or API down: `make demo-offline`. Same four calls, recorded model answers, real checks. It stops at the question and has no agent voice.
- Microphone unusable in the room: stay on the recorded calls.
- A live call passes with nothing to correct: say so, and play a recorded call. Most calls are heard correctly; that is the 70%.

## Questions to expect
- **"Why not just transcribe and fill the form?"** That is 4.1% wrong on the same calls, and it gives up the speech-to-speech model. Pramaan keeps the model and gets to 0.9%.
- **"Two transcribers disagreeing would catch this."** Yes, and it is in the table: On the newest locked set it made no wrong actions against our 2, and asked 18 questions against our 13. On errors the two are within noise; we ask less.
- **"Is this real callers?"** No. Synthetic voices over a simulated phone channel, plus one recorded person so far. The recorder is at `/record.html`.
- **"What does the acoustic model add?"** See the ablation rows; it removes questions on some sets and not on others, and the README says so.
- **"What gets through?"** Calls where every recogniser hears the same wrong value. Two of 220 on the newest locked set.
- **"Latency?"** In live runs the hold was about 350 ms at the median and about 1.6 s at worst (9 calls). The recogniser deadline is 1.2 seconds. The 0 ms in the results table is the offline replay figure.
- **"Does it work on new input?"** `results/fresh_input.md`: 12 new sentences through the live path. The model alone acted on 5 wrong values, Pramaan on none, and it asked on 4. One synthetic voice, so it is not an accuracy estimate.
