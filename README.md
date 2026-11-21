# Pramaan (प्रमाण): evidence-gated actions for voice agents

A speech-to-speech model goes from sound to a tool call with nothing in between to check. Pramaan sits at that
point. When the agent tries to act on a spoken amount, date or phone number, the action is held until
recognisers from different model families, and an open Hindi acoustic model scoring the exact value about to be
executed, support it. If the evidence supports a different value, the argument is corrected. If the evidence is
split, the caller is asked one short question.

Built for the Equal AI Builders hackathon, challenge 2 (Voice AI for India): the same recordings on a base
model and on this system.

## Results

<!-- results:start -->
550 actions, 8 held-out synthetic speakers, phone-grade audio. Policy `f85617771ecb`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 176 (32.0%) | 0 (0.0%) | 0 | 550 |
| Transcribe, then fill the form (B) | 40 (7.3%) | 0 (0.0%) | 0 | 550 |
| Second vendor, then fill the form (V) | 146 (26.5%) | 0 (0.0%) | 0 | 550 |
| Sarvam, then fill the form (S) | 73 (13.3%) | 0 (0.0%) | 0 | 550 |
| Trust one model's confidence (B-LP) | 0 (0.0%) | 550 (100.0%) | 140 | 0 |
| Ask when two models disagree (B-2M) | 10 (1.8%) | 157 (28.5%) | 30 | 393 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 6 (1.1%) | 98 (17.8%) | 34 | 452 |
| Read everything back (A-RB) | 0 (0.0%) | 550 (100.0%) | 176 | 0 |
| **Pramaan** (P) | 10 (1.8%) | 47 (8.5%) | 10 | 503 |

Certificate: of 503 actions Pramaan let through, 10 were wrong; one-sided 95% Clopper-Pearson upper bound 3.4%. Speaker-level: 6 of 8 speakers had any silent error (bound 95.4%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 10 | 47 | 10 |
| without the acoustic model | 11 | 59 | 16 |
| OpenAI transcribers only | 35 | 13 | 9 |
| acoustic model as the only check | 14 | 22 | 8 |
| without the language check (acoustic model also judges English) | 10 | 79 | 10 |
| without Sarvam | 11 | 101 | 18 |
| without the dropped-value check | 20 | 47 | 10 |
| no deadline (wait for every source) | 10 | 50 | 11 |
| deadline 300 ms | 10 | 47 | 10 |
<!-- results:end -->

### Locked set

A second batch of 60 new prompts, weighted towards confusable values (thirteen / thirty, उनतालीस / उनचास,
repeated digits). The tuning speakers' clips from it joined the tuning data; the policy was then frozen, and
the test speakers' clips were scored once.

<!-- fresh:start -->
220 actions, 8 held-out synthetic speakers, phone-grade audio. Policy `f85617771ecb`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 85 (38.6%) | 0 (0.0%) | 0 | 220 |
| Transcribe, then fill the form (B) | 17 (7.7%) | 0 (0.0%) | 0 | 220 |
| Second vendor, then fill the form (V) | 47 (21.4%) | 0 (0.0%) | 0 | 220 |
| Sarvam, then fill the form (S) | 12 (5.5%) | 0 (0.0%) | 0 | 220 |
| Trust one model's confidence (B-LP) | 0 (0.0%) | 220 (100.0%) | 57 | 0 |
| Ask when two models disagree (B-2M) | 3 (1.4%) | 56 (25.5%) | 14 | 164 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 3 (1.4%) | 21 (9.5%) | 14 | 199 |
| Read everything back (A-RB) | 0 (0.0%) | 220 (100.0%) | 85 | 0 |
| **Pramaan** (P) | 3 (1.4%) | 9 (4.1%) | 3 | 211 |

Certificate: of 211 actions Pramaan let through, 3 were wrong; one-sided 95% Clopper-Pearson upper bound 3.6%. Speaker-level: 3 of 8 speakers had any silent error (bound 71.1%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 3 | 9 | 3 |
| without the acoustic model | 3 | 7 | 2 |
| OpenAI transcribers only | 8 | 11 | 6 |
| acoustic model as the only check | 5 | 4 | 1 |
| without the language check (acoustic model also judges English) | 3 | 16 | 3 |
| without Sarvam | 3 | 21 | 4 |
| without the dropped-value check | 6 | 9 | 3 |
| no deadline (wait for every source) | 3 | 10 | 4 |
| deadline 300 ms | 3 | 9 | 3 |
<!-- fresh:end -->

All numbers above come from `make eval`, which replays committed evidence with no model, key or network.
**The speakers are synthetic** (OpenAI text-to-speech voices with varied speaking instructions, passed through an
8 kHz AMR-NB + A-law phone channel, part with babble noise). No human recordings are in the test set yet, so
these numbers say nothing certain about real callers. To test on people: `make serve`, open `/record.html`
(15 prompts per speaker, same phone channel applied on the server), then `make human` once, which scores the
recordings on the frozen policy and writes `results/human.md` without touching the table above.

## Where it wins, ties and loses

<!-- analysis:start -->
Read from the same 550 test actions and frozen policy. Not tuned; the matched rows move only Pramaan's acceptance threshold after the fact.

| Against | Its result | Pramaan with no more questions | Pramaan with no more errors |
|---|---|---|---|
| gpt-transcribe vs VerbX (B-2M) | 10 wrong, 157 asked | 6 wrong, 121 asked | 10 wrong, 47 asked |
| gpt-transcribe vs Sarvam (B-2S) | 6 wrong, 98 asked | 8 wrong, 55 asked | 6 wrong, 121 asked |

Of the 176 actions where the realtime model's value was wrong: 155 repaired to the true value; 11 caller asked; 10 acted on, wrong.
Of the 6 actions where gpt-transcribe and Sarvam agreed on a wrong value (the two-model baseline acts on all of them): Pramaan 4 acted on, wrong; 2 caller asked.

| If a vendor is down | Wrong and acted on | Caller asked |
|---|---|---|
| Pramaan without Sarvam | 11 | 101 |
| Pramaan without VerbX | 7 | 57 |
| Pramaan without OpenAI transcription | 13 | 98 |
| Two-model baseline without Sarvam (falls back to VerbX) | 10 | 157 |

| Slice | Actions | Realtime alone wrong | Sarvam baseline wrong / asked | Pramaan wrong / asked |
|---|---|---|---|---|
| condition: noisy | 150 | 60 (40.0%) | 3 / 33 | 5 / 16 |
| condition: phone | 400 | 116 (29.0%) | 3 / 65 | 5 / 31 |
| language: en | 91 | 3 (3.3%) | 0 / 36 | 1 / 31 |
| language: hi | 459 | 173 (37.7%) | 6 / 62 | 9 / 16 |
| difficulty: confusable | 154 | 37 (24.0%) | 2 / 30 | 0 / 19 |
| difficulty: ordinary | 396 | 139 (35.1%) | 4 / 68 | 10 / 28 |
| values: amount_rupees | 71 | 31 (43.7%) | 0 / 4 | 1 / 1 |
| values: amount_rupees+day_of_month | 180 | 32 (17.8%) | 2 / 45 | 4 / 29 |
| values: amount_rupees+phone | 32 | 14 (43.8%) | 0 / 1 | 0 / 3 |
| values: amount_rupees+weekday | 128 | 39 (30.5%) | 1 / 30 | 4 / 2 |
| values: phone | 102 | 36 (35.3%) | 3 / 10 | 1 / 9 |
| values: phone+weekday | 37 | 24 (64.9%) | 0 / 8 | 0 / 3 |

| Source | Latency p50 | p90 |
|---|---|---|
| gpt-4o-transcribe | 666 ms | 4988 ms |
| gpt-transcribe | 672 ms | 830 ms |
| gpt-transcribe+hints | 680 ms | 852 ms |
| indicconformer-greedy | 1 ms | 1 ms |
| saaras | 333 ms | 400 ms |
| verbx-vocaline | 804 ms | 1145 ms |

Checking one action (5.6 s of audio) costs about $0.0019 in recogniser calls at list prices as of 2026-11-21 ($1.92 per 1,000 actions; VerbX has no public price and is left out; the realtime agent's own cost is the same with or without the guard).

After a question (45 asked test actions replayed live, synthetic cooperative answers): 41 committed right; 1 committed wrong; 3 escalated. Mean questions per asked action 0.89.
<!-- analysis:end -->

Reading it plainly:

- Against the strongest cheap alternative (ask whenever gpt-transcribe and Sarvam disagree), Pramaan asks about
  half as many questions. On the locked set the two make the same number of wrong actions; on the first test
  set Pramaan makes a few more, a difference within noise at this sample size.
- Most of the saving is on Hindi and Hinglish speech, where the acoustic model is in its own language. On
  English turns the acoustic model is not consulted.
- It degrades more gently when a vendor is unavailable, because no single recogniser is required.
- It corrects the speech-to-speech model in place. The two-model baseline is a different product: it throws
  away what the realtime model heard and acts on a transcript.

## Verify in five minutes

```
make setup    # uv sync, then download the 481 MB open acoustic model (needed for live use, not for eval)
make test     # offline
make eval     # offline: prints the table above from data/evidence.jsonl and data/policy.json
make serve    # live demo at http://127.0.0.1:8765 (needs OPENAI_API_KEY; replay mode works without a mic)
make demo-offline   # replay demo with no network or keys (after make setup): recorded model answers, real checks
```

## Demo without a microphone

`make serve`, then open one of these (tuning-speaker clips, replayed through the real models):

- `/?clip=alloy_h33_phone`: the bare model logs a wrong phone number; the guarded model also proposes a wrong one,
  and the evidence corrects it before it executes.
- `/?clip=coral_h16_phone`: the recognisers split on "thirtieth"; the action is held and the agent asks
  "Tees taarikh, ya teen taarikh?".

If the network is down, `make demo-offline` plays the same two clips from `demo/` with nothing leaving the
machine. Both agents then repeat the tool call the realtime model made for that recording, the recognisers
answer from `data/cache.sqlite`, and the acoustic check, the decision and the ledger run for real. The agent's
reply is text only, and a replay stops at the question.

## How it works

```
caller audio ──┬──────────────► gpt-realtime-2.1 ──► tool call (amount, date, phone)
               │ tee                                        │ held
               ▼                                            ▼
   end of turn: speculative fan-out               deadline quorum (tool call + 1.2 s)
   ├─ gpt-transcribe (plain, +domain prompt)                │
   ├─ gpt-4o-transcribe (token log-probabilities)           ▼
   ├─ VerbX Vocaline, Sarvam saaras:v3            typed normaliser ─► value lattice
   └─ IndicConformer Hindi CTC, local CPU ──────► CTC likelihood of every candidate value
                                                  and of its confusable neighbours
                                                            │
                                                  decide(evidence, policy)  ← pure function
                                                            │
                          PASS (execute) · REPAIR (execute the supported value) · ASK one question · BLOCK
                                                            │
                                             ledger (at-most-once) + hash-chained evidence bundle
```

- **Typed normaliser** (`normalise.py`): hand-written inverse text normalisation for Hindi, Hinglish and English in
  Devanagari or Roman script: सवा / साढ़े / पौने / डेढ़ / ढाई, "pachpan sau", lakh and crore, double and triple
  digits, ordinals, weekdays. Values are typed (integer rupees, 10-digit string), so "paune teen hazaar",
  "पौने तीन हज़ार" and "2,750" are the same candidate.
- **Value lattice** (`lattice.py`): candidates per slot with support counted per model family, never per model
  variant. Phone numbers are aligned into a 10-slot confusion network by a weighted edit-distance dynamic
  programme, which also names the contested digit.
- **Acoustic witness** (`witness.py`): the open AI4Bharat IndicConformer Hindi model (ONNX, CPU, about 60 ms per
  turn on a laptop). Its frame posteriors are computed once; each candidate value is then scored by an exact CTC
  forward pass over a graph of its spoken renderings, inside the same sentence context for every candidate, summed
  over tokenisations and spelling variants. The score is a likelihood ratio between the proposed value and the
  best rival, where rivals include values nobody transcribed but a caller could have said (उनतालीस / उनचास,
  thirteen / thirty, a dropped digit). No torch, no forced-alignment library.
- **Decision** (`decide.py`): pure function of the evidence and a frozen policy. Family support and the witness
  are hard predicates; a monotone score is thresholded on top. Live calls and the offline evaluation call the
  same function.
- **Risk gate** (`gate.py`): own exact binomial and Clopper-Pearson; Learn-then-Test fixed-sequence selection;
  speaker-level bound; a betting e-process. The policy is chosen on the tuning speakers only (`eval/tune.py`),
  frozen with a hash, and the certificate is one bound on the test speakers.
- **Deadline-aware evaluation**: every source's latency is recorded with its response. The offline replay drops
  any source that would have missed the live deadline, so the reported numbers are for the system as deployed,
  slow sources included.
- **Executor** (`executor.py`): the guard is the only tool runner. Rows are unique per business operation and
  entity version, so a regenerated tool call cannot execute twice; a caller correction bumps the version and
  voids outstanding confirmations; cancelled responses void.
- **Evidence bundles** (`bundle.py`): canonical JSON, content-addressed, hash-chained; audio by hash only.
  `replay()` re-derives a stored decision and fails on any difference.

## Claims and where to check them

| Claim | Evidence |
|---|---|
| The bare realtime model acts on wrong spoken values often on this test set | arm A in `results/headline.json`; raw responses in `data/cache.sqlite` |
| The open acoustic model separates the true value from confusable ones | `results/g2.json`, `eval/g2.py` |
| Each stage earns its place, or does not | ablation table, `eval/run_eval.py` |
| The bound is honest | `eval/tune.py` touches only tuning speakers; `data/splits.json` was fixed before any result |
| No double execution under barge-in, retries, corrections | `tests/test_executor.py`, `tests/test_live.py` |
| Every number reproduces offline | `make eval` |
| Tests, types and the published tables are checked on every push | `.github/workflows/ci.yml` |
| What happens after a question | `scripts/measure_questions.py`, `results/questions.json` |
| Cost and latency per action | `eval/analysis.py`, `eval/prices.json` (prices with their sources) |

## Limits

- Synthetic speakers only. Real callers, real handsets and real noise are untested.
- The test speakers were evaluated more than once while the system was being built (the repair rule was
  tightened after a first full run, on a defect seen in a tuning clip). The bound is therefore optimistic; a
  clean certificate needs a fresh locked set, ideally human recordings.
- Actions from one speaker are clustered; the action-level bound assumes exchangeable actions. The speaker-level
  bound is printed beside it and is weak with this few speakers.
- The bound covers first-pass decisions (pass and repair). Actions resolved after a question are outside it.
- The question-and-answer path is measured only with synthetic, cooperative answers (the same voice states the
  true value). The answer rule (independent families must agree on the answer; the acoustic model votes but
  cannot veto) was developed on the tuning speakers after a first version escalated most answers; six test
  actions had been replayed under that first version before the change. Two live-path defects found this way
  were fixed: a questioned value the agent later left out could be committed without it, and a value that had
  already passed could be lost the same way.
- A live call is not deterministic: the realtime model does not always make the same tool call for the same
  audio, so live outcomes differ slightly from the offline table.
- The witness is a Hindi model. English number words are scored through Devanagari spellings, which is weaker,
  and without a Devanagari transcript for context the witness abstains.
- VerbX Vocaline's lineage is not documented; it is counted as its own family on that assumption.
- Sarvam was added as a source after the first full results. The policy was re-derived on the tuning speakers
  and came out identical (same hash), but the test speakers have now been scored with and without it; the
  "without Sarvam" ablation row is the earlier system.
- The language check (the Hindi acoustic model is not consulted on turns transcribed entirely in English) was
  added after the first test set showed most questions came from English turns. It was developed and the
  policy re-frozen on the tuning speakers only, with the rule that at least two families must always agree.
  The first test set had been scored several times by then, so its bound is optimistic; the locked set was
  scored once, after the freeze, and is the cleaner number.
- The question-loop measurement covers the first test set only, not the locked set.
- Asking only when gpt-transcribe and Sarvam disagree (B-2S) remains a strong, much simpler baseline. Pramaan's
  measured advantage over it is fewer questions, not fewer errors.
- One human speaker (15 clips) has been recorded and scored; see `results/human.md`. Far too few to rank arms.
- The ElevenLabs Scribe adapter exists but was not run (no key).
- Not claimed: proof, zero error, per-language bounds, or that this is first. Prior art: ROVER and confusion
  networks, inverse text normalisation, likelihood-ratio utterance verification for digit strings (1990s),
  selective classification, Learn-then-Test (Angelopoulos et al., 2021), confirmation dialogues.

## Layout

```
src/pramaan/   types, normalise, render, confusables, lattice, witness, evidence, score, decide, gate,
               question, executor, bundle, cache, pipeline, sources/, live/
eval/          tune.py (policy, tuning speakers only), run_eval.py (all arms, test speakers), analysis.py
               (baselines at matched budgets, slices, cost), g2.py (witness gate)
scripts/       gen_prompts, gen_clips, gen_fresh (locked set), collect, build_evidence, measure_questions,
               fetch_model, selfcheck
data/          prompts, manifest, splits, cache.sqlite (raw responses), evidence.jsonl, policy.json
ui/            live call, evidence and results views
```
