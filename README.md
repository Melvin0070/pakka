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
550 actions, 8 held-out synthetic speakers, phone-grade audio. Policy `50d83054eef1`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 176 (32.0%) | 0 (0.0%) | 0 | 550 |
| Transcribe, then fill the form (B) | 40 (7.3%) | 0 (0.0%) | 0 | 550 |
| Second vendor, then fill the form (V) | 140 (25.5%) | 0 (0.0%) | 0 | 550 |
| Sarvam, then fill the form (S) | 45 (8.2%) | 0 (0.0%) | 0 | 550 |
| Trust one model's confidence (B-LP) | 0 (0.0%) | 550 (100.0%) | 140 | 0 |
| Ask when two models disagree (B-2M) | 10 (1.8%) | 151 (27.5%) | 30 | 399 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 6 (1.1%) | 70 (12.7%) | 34 | 480 |
| Read everything back (A-RB) | 0 (0.0%) | 550 (100.0%) | 176 | 0 |
| **Pramaan** (P) | 10 (1.8%) | 19 (3.5%) | 9 | 531 |

Certificate: of 531 actions Pramaan let through, 10 were wrong; one-sided 95% Clopper-Pearson upper bound 3.2%. Speaker-level: 6 of 8 speakers had any silent error (bound 95.4%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 10 | 19 | 9 |
| without the acoustic model | 11 | 35 | 16 |
| OpenAI transcribers only | 35 | 13 | 9 |
| acoustic model as the only check | 14 | 17 | 7 |
| without the language check (acoustic model also judges English) | 10 | 65 | 9 |
| without Sarvam | 11 | 90 | 16 |
| without the dropped-value check | 20 | 19 | 9 |
| no deadline (wait for every source) | 10 | 22 | 10 |
| deadline 300 ms | 10 | 19 | 9 |
<!-- results:end -->

### Locked set

A second batch of 60 new prompts, weighted towards confusable values (thirteen / thirty, उनतालीस / उनचास,
repeated digits). The tuning speakers' clips from it joined the tuning data; the policy was then frozen, and
the test speakers' clips were scored once.

<!-- fresh:start -->
220 actions, 8 held-out synthetic speakers, phone-grade audio. Policy `50d83054eef1`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 85 (38.6%) | 0 (0.0%) | 0 | 220 |
| Transcribe, then fill the form (B) | 17 (7.7%) | 0 (0.0%) | 0 | 220 |
| Second vendor, then fill the form (V) | 47 (21.4%) | 0 (0.0%) | 0 | 220 |
| Sarvam, then fill the form (S) | 6 (2.7%) | 0 (0.0%) | 0 | 220 |
| Trust one model's confidence (B-LP) | 0 (0.0%) | 220 (100.0%) | 57 | 0 |
| Ask when two models disagree (B-2M) | 3 (1.4%) | 56 (25.5%) | 14 | 164 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 3 (1.4%) | 15 (6.8%) | 14 | 205 |
| Read everything back (A-RB) | 0 (0.0%) | 220 (100.0%) | 85 | 0 |
| **Pramaan** (P) | 4 (1.8%) | 3 (1.4%) | 2 | 217 |

Certificate: of 217 actions Pramaan let through, 4 were wrong; one-sided 95% Clopper-Pearson upper bound 4.2%. Speaker-level: 3 of 8 speakers had any silent error (bound 71.1%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 4 | 3 | 2 |
| without the acoustic model | 3 | 4 | 2 |
| OpenAI transcribers only | 8 | 11 | 6 |
| acoustic model as the only check | 5 | 2 | 1 |
| without the language check (acoustic model also judges English) | 4 | 13 | 2 |
| without Sarvam | 4 | 18 | 2 |
| without the dropped-value check | 7 | 3 | 2 |
| no deadline (wait for every source) | 4 | 4 | 3 |
| deadline 300 ms | 4 | 3 | 2 |
<!-- fresh:end -->

### Locked set 2

After locked set 1, two defects found on the tuning speakers were fixed: the normaliser missed some ways a
recogniser writes an English date ("ऑन द २८", "15थ"), and malformed short phone numbers were allowed to outrank
complete ones in the acoustic check. The first test set and locked set 1 above are shown with those fixes, so
they have now been scored more than once. Locked set 2 is a further 60 new prompts on the test speakers,
generated after the fixes and scored once.

<!-- fresh2:start -->
220 actions, 8 held-out synthetic speakers, phone-grade audio. Policy `50d83054eef1`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 65 (29.5%) | 0 (0.0%) | 0 | 220 |
| Transcribe, then fill the form (B) | 9 (4.1%) | 0 (0.0%) | 0 | 220 |
| Second vendor, then fill the form (V) | 59 (26.8%) | 0 (0.0%) | 0 | 220 |
| Sarvam, then fill the form (S) | 11 (5.0%) | 0 (0.0%) | 0 | 220 |
| Trust one model's confidence (B-LP) | 0 (0.0%) | 220 (100.0%) | 40 | 0 |
| Ask when two models disagree (B-2M) | 2 (0.9%) | 63 (28.6%) | 7 | 157 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 0 (0.0%) | 18 (8.2%) | 9 | 202 |
| Read everything back (A-RB) | 0 (0.0%) | 220 (100.0%) | 65 | 0 |
| **Pramaan** (P) | 2 (0.9%) | 13 (5.9%) | 6 | 207 |

Certificate: of 207 actions Pramaan let through, 2 were wrong; one-sided 95% Clopper-Pearson upper bound 3.0%. Speaker-level: 2 of 8 speakers had any silent error (bound 60.0%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 2 | 13 | 6 |
| without the acoustic model | 2 | 10 | 6 |
| OpenAI transcribers only | 5 | 6 | 5 |
| acoustic model as the only check | 3 | 7 | 4 |
| without the language check (acoustic model also judges English) | 2 | 21 | 6 |
| without Sarvam | 3 | 39 | 10 |
| without the dropped-value check | 2 | 13 | 6 |
| no deadline (wait for every source) | 2 | 13 | 6 |
| deadline 300 ms | 2 | 13 | 6 |
<!-- fresh2:end -->

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
| gpt-transcribe vs VerbX (B-2M) | 10 wrong, 151 asked | 6 wrong, 108 asked | 10 wrong, 19 asked |
| gpt-transcribe vs Sarvam (B-2S) | 6 wrong, 70 asked | 8 wrong, 25 asked | 6 wrong, 108 asked |

Of the 176 actions where the realtime model's value was wrong: 157 repaired to the true value; 10 acted on, wrong; 9 caller asked.
Of the 6 actions where gpt-transcribe and Sarvam agreed on a wrong value (the two-model baseline acts on all of them): Pramaan 4 acted on, wrong; 2 caller asked.

| If a vendor is down | Wrong and acted on | Caller asked |
|---|---|---|
| Pramaan without Sarvam | 11 | 90 |
| Pramaan without VerbX | 7 | 27 |
| Pramaan without OpenAI transcription | 11 | 88 |
| Two-model baseline without Sarvam (falls back to VerbX) | 10 | 151 |

| Slice | Actions | Realtime alone wrong | Sarvam baseline wrong / asked | Pramaan wrong / asked |
|---|---|---|---|---|
| condition: noisy | 150 | 60 (40.0%) | 3 / 23 | 5 / 4 |
| condition: phone | 400 | 116 (29.0%) | 3 / 47 | 5 / 15 |
| language: en | 91 | 3 (3.3%) | 0 / 8 | 1 / 7 |
| language: hi | 459 | 173 (37.7%) | 6 / 62 | 9 / 12 |
| difficulty: confusable | 154 | 37 (24.0%) | 2 / 17 | 0 / 6 |
| difficulty: ordinary | 396 | 139 (35.1%) | 4 / 53 | 10 / 13 |
| values: amount_rupees | 71 | 31 (43.7%) | 0 / 4 | 1 / 1 |
| values: amount_rupees+day_of_month | 180 | 32 (17.8%) | 2 / 17 | 4 / 5 |
| values: amount_rupees+phone | 32 | 14 (43.8%) | 0 / 1 | 0 / 1 |
| values: amount_rupees+weekday | 128 | 39 (30.5%) | 1 / 30 | 4 / 2 |
| values: phone | 102 | 36 (35.3%) | 3 / 10 | 1 / 8 |
| values: phone+weekday | 37 | 24 (64.9%) | 0 / 8 | 0 / 2 |

| Source | Latency p50 | p90 |
|---|---|---|
| gpt-4o-transcribe | 666 ms | 4988 ms |
| gpt-transcribe | 672 ms | 830 ms |
| gpt-transcribe+hints | 680 ms | 852 ms |
| indicconformer-greedy | 1 ms | 1 ms |
| saaras | 333 ms | 400 ms |
| verbx-vocaline | 804 ms | 1145 ms |

Checking one action (5.6 s of audio) costs about $0.0019 in recogniser calls at list prices as of 2026-11-21 ($1.92 per 1,000 actions; VerbX has no public price and is left out; the realtime agent's own cost is the same with or without the guard).

After a question (17 asked test actions replayed live, synthetic cooperative answers): 12 committed right; 2 committed wrong; 3 escalated. Mean questions per asked action 0.82.
<!-- analysis:end -->

Reading it plainly:

- Against the strongest cheap alternative (ask whenever gpt-transcribe and Sarvam disagree), Pramaan asks
  fewer questions on every set, and makes the same or slightly more wrong actions. On locked set 2 that is 13
  questions and 2 wrong against 18 questions and none. The error differences are within noise at these sizes.
- Most of the saving is on Hindi and Hinglish speech, where the acoustic model is in its own language. On
  English turns the acoustic model is not consulted.
- It degrades more gently when a vendor is unavailable, because no single recogniser is required.
- It corrects the speech-to-speech model in place. The two-model baseline is a different product: it throws
  away what the realtime model heard and acts on a transcript.

## The other direction: numbers the voice says

The same fault runs the other way. A speech generator handed "₹2,75,350" or "9876004321" has to turn digits
into words itself, and it drops digits, changes the scale or reads the figure haltingly. Here the intended value
is known, so the check is narrower than on the hearing side: two recognisers from different families must read
that value back, and on Hindi clips the acoustic model must rate it above every look-alike value, inside the
script's own sentence. A failed check costs one more take, not a question to a caller, so any doubt fails.

Three ways of producing each clip, same sentence and voice: **digits** (the script as written), **words** (the
number spelt out in the target language by the same number grammar the hearing side parses with), and
**checked** (words, then up to three takes until one passes). "Nobody heard it" means none of four recognisers
read the intended number, which does not depend on the check's own strictness.

<!-- speak:start -->
360 script and voice pairs (3 generators, 2 voices each, Hindi and English; amounts, phone numbers, dates), 953 clips, 92 minutes of generated speech.

| | Pairs | Digits: nobody heard the number | Digits: not verified | Words: nobody heard it | Words: not verified | Checked: no take passed | Takes per clip |
|---|---|---|---|---|---|---|---|
| **All** | 360 | 159 (44.2%) | 183 (50.8%) | 15 (4.2%) | 45 (12.5%) | 16 (4.4%) | 1.18 |
| gpt-4o-mini-tts | 120 | 52 (43.3%) | 60 (50.0%) | 0 (0.0%) | 7 (5.8%) | 1 (0.8%) | 1.08 |
| gpt-audio-1.5 | 120 | 38 (31.7%) | 41 (34.2%) | 3 (2.5%) | 13 (10.8%) | 4 (3.3%) | 1.14 |
| tts-1 | 120 | 69 (57.5%) | 82 (68.3%) | 12 (10.0%) | 25 (20.8%) | 11 (9.2%) | 1.32 |
| Hindi | 180 | 119 (66.1%) | 127 (70.6%) | 14 (7.8%) | 29 (16.1%) | 12 (6.7%) | 1.24 |
| English | 180 | 40 (22.2%) | 56 (31.1%) | 1 (0.6%) | 16 (8.9%) | 4 (2.2%) | 1.12 |
| amount rupees | 144 | 81 (56.2%) | 96 (66.7%) | 1 (0.7%) | 16 (11.1%) | 6 (4.2%) | 1.17 |
| phone | 144 | 69 (47.9%) | 75 (52.1%) | 14 (9.7%) | 27 (18.8%) | 10 (6.9%) | 1.27 |
| day of month | 72 | 9 (12.5%) | 12 (16.7%) | 0 (0.0%) | 2 (2.8%) | 0 (0.0%) | 1.03 |

Held-out recognisers (never used by the check) on the clips each arm would ship:

| Held-out recogniser | Digits | Words | Checked |
|---|---|---|---|
| gpt-4o-transcribe hears another number | 133 of 322 (41.3%) | 55 of 354 (15.5%) | 38 of 340 (11.2%) |
| verbx-vocaline hears another number | 29 of 40 (72.5%) | 16 of 51 (31.4%) | 15 of 45 (33.3%) |

Acoustic model (Hindi clips): of 294 clips both recognisers read correctly, it vetoed 4 (2 of those also disputed by a held-out recogniser) and passed 290 (58 disputed).

Where gpt-4o-transcribe disputed a checked Hindi clip (36 clips), the acoustic model was asked to choose between the intended value and the disputed reading: it sided with the intended value in 36, with the other reading in 0, and was undecided in 0 (margin 3 nats). `scripts/speak/adjudicate.py`.

Pauses inside the number (verified Hindi clips, first take):

| Kind | Script | Clips | Median longest pause | Clips with a pause of 300 ms or more | Median time on the number |
|---|---|---|---|---|---|
| amount rupees | digits | 15 | 0 ms | 0 (0.0%) | 1.28 s |
| amount rupees | words | 64 | 0 ms | 6 (9.4%) | 1.48 s |
| phone | digits | 14 | 300 ms | 8 (57.1%) | 3.28 s |
| phone | words | 53 | 460 ms | 39 (73.6%) | 4.08 s |
<!-- speak:end -->

`make speak-eval` rebuilds this table offline from `data/speak/evidence.jsonl`. `make speak-run` regenerates
the clips (needs keys; the audio is not committed). The page is `/speak.html`: recorded pairs to listen to, and
a box that generates and checks any number live. One clip from anywhere, video included:

```
uv run python -m pramaan.speak clip.mp4 --amount 275350 --lang hi \
    --script "आपका दो लाख पचहत्तर हज़ार तीन सौ पचास रुपये का भुगतान अभी बाकी है।"
```

What this does not show:

- No video generator was tested: the key used has none. The three generators are OpenAI's (`tts-1`,
  `gpt-4o-mini-tts`, and `gpt-audio-1.5`, which writes audio directly as a video model's sound track is
  written). For a video clip the check runs on the audio track; the repair is another generation.
- Nobody has listened to the clips at scale. Every label comes from recognisers, which mishear numbers
  themselves, so "not verified" overstates the fault and "nobody heard it" understates it. How many checked
  clips still carry a wrong number is therefore not known; the held-out rows are the only outside evidence.
- VerbX was rate-limited for most of the run and answered on about a fifth of the clips.
- Three takes were made for some clips that needed fewer, because one recogniser was down during part of the
  run; the takes column counts only those the loop needs once every recogniser has answered.
- The check's rule was fixed before the run and nothing was tuned, so there is no tuning split here.
- Hindi and English only. The number-to-words step and the acoustic model are per language; other languages
  would rest on recogniser agreement alone until both are written.
- The pause measure is a diagnostic, not part of the check, and has no listener study behind it.
- A clip that fails three takes is flagged, not fixed.
- Not new in its parts. Spelling numbers out before synthesis is text normalisation (PolyNorm, EMNLP 2025;
  EmergentTTS-Eval, 2025); transcribing synthetic speech and regenerating on a mismatch is a known data-cleaning
  step (S3-Bench, 2026). Known from search summaries, not read in full. What is added here is a typed value
  check with an acoustic likelihood ratio against look-alike values, and a measurement on Indian number forms.

## Verify in five minutes

```
make setup    # uv sync, then download the 481 MB open acoustic model (needed for live use, not for eval)
make test     # offline
make eval     # offline: prints the table above from data/evidence.jsonl and data/policy.json
make serve    # live demo at http://127.0.0.1:8765 (needs OPENAI_API_KEY; replay mode works without a mic)
make demo-offline   # replay demo with no network or keys (after make setup): recorded model answers, real checks
```

## Demo without a microphone

`make serve`, then open http://127.0.0.1:8765. The first view shows the before and after numbers and four
recorded calls (`demo/scenarios.json`) that play through the real models: an amount the agent dropped, a
wrong phone digit, a split that leads to one question, and a misheard Hindi fraction. `DEMO.md` is the
two-minute run of show, with how often each call reproduced live.

If the network is down, `make demo-offline` plays the same calls from `demo/` with nothing leaving the
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
- The question-loop measurement covers the first test set only and replays the calls live, so the model and
  the recognisers can answer differently from the cached scoring run. Under the current policy
  (`50d83054eef1`) 17 calls were replayed: 12 ended right, 3 escalated and 2 committed a wrong value. Both wrong
  commits were first-pass repairs made without a question, one amount (900 for 875) and one phone digit.
- The acoustic model's contribution is not consistent. It removes questions on the tuning speakers (22 to 13)
  and on the first test set (35 to 19), but not on either locked set. It picks the true value among confusable
  candidates in 591 of 600 Hindi cases on the tuning speakers; it is rarely decisive because the transcribers
  usually already agree.
- Asking only when gpt-transcribe and Sarvam disagree (B-2S) remains a strong, much simpler baseline. Pramaan's
  measured advantage over it is fewer questions, not fewer errors.
- One human speaker (15 clips) has been recorded and scored; see `results/human.md`. Far too few to rank arms.
- The ElevenLabs Scribe adapter exists but was not run (no key).
- Not claimed: proof, zero error, per-language bounds, or that this is first. Prior art: ROVER and confusion
  networks, inverse text normalisation, likelihood-ratio utterance verification for digit strings (1990s),
  selective classification, Learn-then-Test (Angelopoulos et al., 2021), confirmation dialogues.

## Layout

```
src/pramaan/speak/  verbalise, generators, check, prosody, loop, api (the speaking side)
src/pramaan/   types, normalise, render, confusables, lattice, witness, evidence, score, decide, gate,
               question, executor, bundle, cache, pipeline, sources/, live/
eval/          tune.py (policy, tuning speakers only), run_eval.py (all arms, test speakers), analysis.py
               (baselines at matched budgets, slices, cost), g2.py (witness gate)
scripts/       gen_prompts, gen_clips, gen_fresh (locked set), collect, build_evidence, measure_questions,
               fetch_model, selfcheck
data/          prompts, manifest, splits, cache.sqlite (raw responses), evidence.jsonl, policy.json
ui/            live call, evidence and results views
```
