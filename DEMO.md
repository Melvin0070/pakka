# Demo runbook

## Before the slot
1. `make demo` (self-check, then the server). Open http://127.0.0.1:8765 in Chrome with a headset.
2. Play "An amount the agent left out" once to warm the models.
3. Have `make demo-offline` ready in a second terminal in case the network fails.

## Two minutes
| Time | Screen | Say |
|---|---|---|
| 0:00 | Demo, comparison at the top | "A speech-to-speech agent goes from sound straight to action. Even prompted specifically for Indian numbers, it acted on a wrong amount, date or phone number on 18.2% of the same recorded calls. With Pakka checking each action, 0.5%, with a question on 4.5% of calls." |
| 0:25 | Demo: click "An amount the agent left out" | "Left: the model alone logs Thursday and drops the amount. Right: the same model, held for about a second, and the amount is restored from the evidence." |
| 0:50 | Demo: click "Evidence is split, so it asks" | "Here the recognisers disagree on one digit, so the agent asks about that digit only, and commits after the answer." |
| 1:20 | Evidence | "Every decision is recorded: what each recogniser heard, when it answered, and why the action went through." |
| 1:35 | Demo: "Use your voice" | Ask a judge to say an amount and a date in Hindi or Hinglish. |
| 1:55 | Results | "Every number here is reproduced offline by `make eval`, including the baselines we did not beat on errors." |

## Which calls to trust live
Five live runs each, real models. Both panes show the same tool call from one realtime session:

| Call | Model's call wrong | Pakka right |
|---|---|---|
| An amount the agent left out | 5 of 5 | 5 of 5 |
| One digit of a phone number | 1 of 5 | 5 of 5 |
| Evidence is split, so it asks | 5 of 5 | 5 of 5 |
| A Hindi fraction, misheard | 5 of 5 | 5 of 5 |

Lead with the first and third, then the fraction. Skip the phone digit unless there is time: the guarded agent
now usually hears it correctly, so both panes agree. The model does not make the identical mistake each time
(the fraction came out as ₹2,00,000 three times and ₹2,12,500 twice).

## Telugu (optional, about 30 seconds)
`make serve-te` in a second terminal, then http://127.0.0.1:8766. Same page, Telugu recognisers, the Telugu
acoustic model, Telugu questions and four recorded Telugu calls (`demo/scenarios.te.json`).

Say: "Nothing in the decision rule knows Hindi. For Telugu we swapped the number lexicon and the open acoustic
model, and kept the policy that was frozen on Hindi." Play "తొంభై heard as తొమ్మిది": the model alone logs
₹9,000, the guarded side logs ₹90,000. Then the Results tab, "Telugu".

With no keys or network: `make demo-offline` covers the Hindi calls, `make demo-offline-te` the Telugu ones.

## If something breaks
- Network or API down: `make demo-offline`. Same four calls, recorded model answers, real checks. It stops at the question and has no agent voice.
- Microphone unusable in the room: stay on the recorded calls.
- A live call passes with nothing to correct: say so, and play a recorded call. Most calls are heard correctly; that is the other 82%.

## Questions to expect
- **"Why not just transcribe and fill the form?"** That is 4.1% wrong on the same calls, and it gives up the speech-to-speech model. Pakka keeps the model and gets to 0.5%.
- **"Your model-alone baseline has a weak prompt."** We tested that. With a prompt that teaches Hindi fractions, lakh and crore, and digit handling, the model alone is still wrong on 40 of 220 calls (18.2%, down from 29.5%). Pakka on that better agent: 1 wrong (0.5%), 10 asked (4.5%). `results/strong_baseline.json`.
- **"Two transcribers disagreeing would catch this."** Yes, and it is in the table: On the newest locked set it made no wrong actions against our 1, and asked 18 questions against our 10. On errors the two are within noise; we ask less.
- **"Is this real callers?"** No. Synthetic voices over a simulated phone channel, plus one recorded person so far. The recorder is at `/record.html`.
- **"What does the acoustic model add?"** See the ablation rows; it removes questions on some sets and not on others, and the README says so.
- **"What gets through?"** Calls where at least two recogniser families agree on the same wrong value, sometimes over a third that dissents. With the original short prompt, two of 220 on the newest locked set, both ₹2,750 heard as ₹3,000 with Sarvam dissenting. Across all three synthetic sets, every family agreed on the wrong value in 4 of the 14 errors.
- **"Latency?"** In live runs the hold was about 350 ms at the median and about 1.6 s at worst (9 calls). The recogniser deadline is 1.2 seconds. The 0 ms in the results table is the offline replay figure.
- **"Does it work on new input?"** `results/fresh_input.md`: 12 new sentences through the live path. The model alone acted on 5 wrong values, Pakka on none, and it asked on 4. One synthetic voice, so it is not an accuracy estimate.
