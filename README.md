# Pramaan (प्रमाण): evidence-gated actions for voice agents

A speech-to-speech model goes from sound to a tool call with nothing in between to check. Pramaan sits at that
point. When the agent tries to act on a spoken amount, date or phone number, the action is held until
recognisers from different model families, and an open Hindi acoustic model scoring the exact value about to be
executed, support it. If the evidence supports a different value, the argument is corrected. If the evidence is
split, the caller is asked one short question.

Built for the Equal AI Builders hackathon, challenge 2 (Voice AI for India): the same recordings on a base
model and on this system.

## Live

- Hindi: https://pramaan-voice.vercel.app
- Telugu: https://pramaan-voice-te.vercel.app

Both run in replay mode and call no paid API: the recorded calls play, every recogniser answers from the
committed cache, and the acoustic check, the decision and the ledger are computed on the server for each play.
The microphone is off there; for live speech run `make serve` or `make serve-te` with your own keys. `main.py`
is the hosted entrypoint and forces replay mode, and `make deploy` republishes both.

## Results

<!-- results:start -->
550 actions, 8 held-out synthetic speakers, phone-grade audio. Policy `50d83054eef1`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 176 (32.0%) | 0 (0.0%) | 0 | 550 |
| Transcribe, then fill the form (B) | 40 (7.3%) | 0 (0.0%) | 0 | 550 |
| Second vendor, then fill the form (V) | 140 (25.5%) | 0 (0.0%) | 0 | 550 |
| Sarvam, then fill the form (S) | 45 (8.2%) | 0 (0.0%) | 0 | 550 |
| Trust one model's confidence; none certifies, so it always asks (B-LP) | 0 (0.0%) | 550 (100.0%) | 140 | 0 |
| Ask when two models disagree (B-2M) | 10 (1.8%) | 151 (27.5%) | 30 | 399 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 6 (1.1%) | 70 (12.7%) | 34 | 480 |
| Read everything back (A-RB) | 0 (0.0%) | 550 (100.0%) | 176 | 0 |
| **Pramaan** (P) | 9 (1.6%) | 31 (5.6%) | 21 | 519 |

Certificate: of 519 actions Pramaan let through, 9 were wrong; one-sided 95% Clopper-Pearson upper bound 3.0%. Speaker-level: 6 of 8 speakers had any silent error (bound 95.4%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 9 | 31 | 21 |
| without the acoustic model | 10 | 45 | 26 |
| OpenAI transcribers only | 35 | 13 | 9 |
| acoustic model as the only check | 14 | 25 | 15 |
| without the language check (acoustic model also judges English) | 9 | 77 | 21 |
| without Sarvam | 11 | 97 | 23 |
| without the dropped-value check | 18 | 31 | 21 |
| no deadline (wait for every source) | 9 | 34 | 22 |
| deadline 300 ms | 9 | 31 | 21 |
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
| Trust one model's confidence; none certifies, so it always asks (B-LP) | 0 (0.0%) | 220 (100.0%) | 57 | 0 |
| Ask when two models disagree (B-2M) | 3 (1.4%) | 56 (25.5%) | 14 | 164 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 3 (1.4%) | 15 (6.8%) | 14 | 205 |
| Read everything back (A-RB) | 0 (0.0%) | 220 (100.0%) | 85 | 0 |
| **Pramaan** (P) | 3 (1.4%) | 4 (1.8%) | 3 | 216 |

Certificate: of 216 actions Pramaan let through, 3 were wrong; one-sided 95% Clopper-Pearson upper bound 3.5%. Speaker-level: 3 of 8 speakers had any silent error (bound 71.1%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 3 | 4 | 3 |
| without the acoustic model | 3 | 4 | 2 |
| OpenAI transcribers only | 8 | 11 | 6 |
| acoustic model as the only check | 5 | 2 | 1 |
| without the language check (acoustic model also judges English) | 3 | 14 | 3 |
| without Sarvam | 4 | 18 | 2 |
| without the dropped-value check | 6 | 4 | 3 |
| no deadline (wait for every source) | 3 | 5 | 4 |
| deadline 300 ms | 3 | 4 | 3 |
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
| Trust one model's confidence; none certifies, so it always asks (B-LP) | 0 (0.0%) | 220 (100.0%) | 40 | 0 |
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
recordings on the frozen policy and writes `results/human.md` without touching the table above. The recorder
serves `data/human/prompts.jsonl`: 150 prompts for ten people, with values absent from every synthetic batch.

After those 15 lines each person reads a made-up PIN code and account number and answers five forced-choice
questions in their own words. These stay out of the locked set; `make human-extras` scores them into
`results/human_extras.json`. Answers are judged worst-case, with the agent still holding the wrong option, and
without the agent's own next turn. A short answer ("saat", "doosra wala") counts only when at least two
independent recogniser families name the same option and none hears another. PIN and account values are
recognised only after a spoken label, and this path has no recorded results from people yet.

### Telugu, on the policy frozen on Hindi

A second language is a number lexicon, a renderer and a swap of the open acoustic model (IndicConformer
Telugu, same architecture, same numpy CTC code). The lattice, the decision rule and the policy are untouched:
the Telugu calls below are judged by policy `50d83054eef1`, whose thresholds were chosen on Hindi speakers.
60 Telugu prompts, weighted towards pairs a Telugu listener confuses (ఇరవై / అరవై, పదిహేను / పదిహేడు,
తొమ్మిది / తొంభై), on the same twelve voices and the same speaker split. The four tuning speakers' Telugu
clips were used to fix the Telugu parser on real recogniser output; the eight test speakers were scored once.

<!-- te:start -->
220 Telugu actions, 8 held-out synthetic speakers, phone-grade audio. Policy `50d83054eef1`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 85 (38.6%) | 0 (0.0%) | 0 | 220 |
| Transcribe, then fill the form (B) | 31 (14.1%) | 0 (0.0%) | 0 | 220 |
| Second vendor, then fill the form (V) | 38 (17.3%) | 0 (0.0%) | 0 | 220 |
| Sarvam, then fill the form (S) | 24 (10.9%) | 0 (0.0%) | 0 | 220 |
| Trust one model's confidence; none certifies, so it always asks (B-LP) | 0 (0.0%) | 220 (100.0%) | 84 | 0 |
| Ask when two models disagree (B-2M) | 7 (3.2%) | 46 (20.9%) | 24 | 174 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 8 (3.6%) | 32 (14.5%) | 23 | 188 |
| Read everything back (A-RB) | 0 (0.0%) | 220 (100.0%) | 85 | 0 |
| **Pramaan** (P) | 7 (3.2%) | 17 (7.7%) | 13 | 203 |

Certificate: of 203 actions Pramaan let through, 7 were wrong; one-sided 95% Clopper-Pearson upper bound 6.4%. Speaker-level: 4 of 8 speakers had any silent error (bound 80.7%). Added hold p50 0 ms, p95 0 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 7 | 17 | 13 |
| without the acoustic model | 6 | 21 | 16 |
| OpenAI transcribers only | 16 | 21 | 14 |
| acoustic model as the only check | 10 | 21 | 9 |
| without the language check (acoustic model also judges English) | 7 | 15 | 12 |
| without Sarvam | 6 | 24 | 15 |
| without the dropped-value check | 11 | 17 | 13 |
| no deadline (wait for every source) | 7 | 17 | 13 |
| deadline 300 ms | 7 | 17 | 13 |

Telugu acoustic model alone: the true value outscored every transcribed and confusable rival in 321 of 336 values it scored.
<!-- te:end -->

Reading it plainly: the model alone acts on a wrong Telugu value on 38.6% of calls; Pramaan on 3.2%, asking on
7.7%. Asking whenever gpt-transcribe and Sarvam disagree gets 3.6% while asking on 14.5%. The upper bound
here is 6.4%, above the 5% the policy was frozen for on Hindi: an untuned transfer, and these 220 calls are too
few to separate 7 errors from 8. Single-recogniser pipelines are much weaker in Telugu than in Hindi (10.9% to
17.3% wrong), which is where agreement across families earns more.

What changes with the language sits in the lexer: a Telugu scale alone means one of it (లక్ష యాభై వేలు is
1,50,000), scales inflect (వందలు, వందల, వేలకు), halves and quarters are suffixes on the multiplier
(రెండున్నర వేలు, లక్షన్నర, రెండుంపావు లక్షలు), ten and unit fuse (డెబ్బయైదు), and recognisers often write a
number as one word (రెండువేల). `tests/test_telugu.py` checks that every rendering of every amount parses back
to its value. `make te` reprints the table offline; `make serve-te` runs the live demo in Telugu on port 8766.

### With a stronger agent prompt

The agent in the tables above has a short, generic prompt. `make strong-baseline` reruns locked set 2 with a
prompt that teaches Hindi fractions, lakh and crore, and digit handling, under the same frozen policy. The model
alone is wrong on 40 of 220 calls (18.2%, against 29.5%). Pramaan on that agent is wrong on 1 (0.5%) and asks on
10 (4.5%). The prompt was written once, after this set's earlier results had been seen; its worked examples
avoid every amount in the set. Results are in `results/strong_baseline.json`; `make strong-baseline` rescoring
needs the clips regenerated under `data/clips`, which are not in the repository.

## Where it wins, ties and loses

<!-- analysis:start -->
Read from the same 550 test actions and frozen policy. Not tuned; the matched rows move only Pramaan's acceptance threshold after the fact.

| Against | Its result | Pramaan with no more questions | Pramaan with no more errors |
|---|---|---|---|
| gpt-transcribe vs VerbX (B-2M) | 10 wrong, 151 asked | 5 wrong, 118 asked | 9 wrong, 31 asked |
| gpt-transcribe vs Sarvam (B-2S) | 6 wrong, 70 asked | 7 wrong, 37 asked | 6 wrong, 117 asked |

Of the 176 actions where the realtime model's value was wrong: 146 repaired to the true value; 21 caller asked; 9 acted on, wrong.
Of the 6 actions where gpt-transcribe and Sarvam agreed on a wrong value (the two-model baseline acts on all of them): Pramaan 4 acted on, wrong; 2 caller asked.

| If a vendor is down | Wrong and acted on | Caller asked |
|---|---|---|
| Pramaan without Sarvam | 11 | 97 |
| Pramaan without VerbX | 6 | 37 |
| Pramaan without OpenAI transcription | 10 | 91 |
| Two-model baseline without Sarvam (falls back to VerbX) | 10 | 151 |

| Slice | Actions | Realtime alone wrong | Sarvam baseline wrong / asked | Pramaan wrong / asked |
|---|---|---|---|---|
| condition: noisy | 150 | 60 (40.0%) | 3 / 23 | 5 / 7 |
| condition: phone | 400 | 116 (29.0%) | 3 / 47 | 4 / 24 |
| language: en | 91 | 3 (3.3%) | 0 / 8 | 1 / 7 |
| language: hi | 459 | 173 (37.7%) | 6 / 62 | 8 / 24 |
| difficulty: confusable | 154 | 37 (24.0%) | 2 / 17 | 0 / 7 |
| difficulty: ordinary | 396 | 139 (35.1%) | 4 / 53 | 9 / 24 |
| values: amount_rupees | 71 | 31 (43.7%) | 0 / 4 | 1 / 3 |
| values: amount_rupees+day_of_month | 180 | 32 (17.8%) | 2 / 17 | 3 / 8 |
| values: amount_rupees+phone | 32 | 14 (43.8%) | 0 / 1 | 0 / 1 |
| values: amount_rupees+weekday | 128 | 39 (30.5%) | 1 / 30 | 4 / 5 |
| values: phone | 102 | 36 (35.3%) | 3 / 10 | 1 / 11 |
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

After a question (29 asked test actions replayed live, synthetic cooperative answers): 26 committed right; 3 escalated. 7 of the committed passed live with no question, so 22 were actually asked. Mean questions per asked action 0.97.
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

Both panes show one tool call from one realtime session: the left executes it as it stands, the right holds
it for the check. `/ws?left=independent` runs a second, bare agent on the left instead.

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

- **Typed normaliser** (`normalise.py`): hand-written inverse text normalisation for Hindi, Hinglish, Telugu and
  English in Devanagari, Telugu or Roman script: सवा / साढ़े / पौने / डेढ़ / ढाई, "pachpan sau", lakh and crore, double and triple
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
- **Risk gate** (`gate.py`): own exact binomial and Clopper-Pearson, and a speaker-level bound. The policy is
  chosen on the tuning speakers only (`eval/tune.py`: the most permissive grid point that passes a binomial
  test there, uncorrected for the grid), frozen with a hash, and the certificate is one bound on the test
  speakers. Learn-then-Test fixed-sequence selection sets the threshold of the log-probability baseline; a
  betting e-process is implemented and tested but does not choose anything.
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
| The open acoustic model separates the true value from confusable ones | `results/g2.json` (written by `eval/g2.py`, which needs the early probe clips under `g0/clips`, not in the repository) |
| Each stage earns its place, or does not | ablation table, `eval/run_eval.py` |
| The bound is honest | `eval/tune.py` touches only tuning speakers; `data/splits.json` was fixed before any result |
| No double execution under barge-in, retries, corrections | `tests/test_executor.py`, `tests/test_live.py` |
| Every number reproduces offline | `make eval` |
| Tests, types (`src`, `eval`, `scripts`) and the published tables are checked on every push | `.github/workflows/ci.yml` |
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
- The witness is a Hindi model (or the Telugu one under `PRAMAAN_LANG=te`). English number words are scored
  through Devanagari or Telugu spellings, which is weaker, and without a transcript in the model's own script
  for context the witness abstains.
- One language per deployment: `PRAMAAN_LANG` picks the recogniser settings and the acoustic model at start.
  A call that switches between Hindi and Telugu is not routed between the two models.
- Telugu has no tuned policy, no locked second set, no human recordings and no measured question loop. Its
  questions are phrased in Telugu but have not been played to a Telugu speaker. Tamil is not built.
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
  the recognisers can answer differently from the cached scoring run. Its first run under the current policy
  committed 2 wrong values of 17, both first-pass repairs made while one recogniser family heard a third
  value. A repair is now refused in that case and the caller is asked instead. The rule was checked on the
  tuning speakers (2 of 13 such repairs were wrong, 0 of 86 others) but it was prompted by test-set failures,
  so the first test set and locked set 1 are optimistic on this point. It costs questions: 19 to 31 on the
  first test set. Locked set 2 has no such repair and its numbers did not move. After the change 29 calls were
  replayed: 26 ended right, 3 escalated, none committed a wrong value. Seven of the 26 passed live with no
  question, so 22 calls were actually asked: 19 ended right and 3 escalated. Two of the 31 asked offline were
  not replayed, because the slot in question was one the caller never gave.
- The acoustic model's contribution is not consistent. It removes questions on the tuning speakers (30 to 24)
  and on the first test set (45 to 31), makes no difference on locked set 1 (4 either way) and adds three on
  locked set 2 (10 to 13). On the tuning speakers the true value outscores every transcribed and confusable
  rival in 655 of the 705 values it scored; it is rarely decisive because the transcribers usually already
  agree.
- Asking only when gpt-transcribe and Sarvam disagree (B-2S) remains a strong, much simpler baseline. Pramaan's
  measured advantage over it is fewer questions, not fewer errors.
- One human speaker (15 clips) has been recorded and scored; see `results/human_pilot.md`. It is the author,
  on prompts the tuning voices also spoke, scored more than once, so it is a pilot and stays out of the locked
  human set, which `/record.html` will write to `data/human/manifest.jsonl`. Far too few to rank arms.
- The ElevenLabs Scribe adapter exists but was not run (no key).
- Not claimed: proof, zero error, per-language bounds, or that this is first. Prior art: ROVER and confusion
  networks, inverse text normalisation, likelihood-ratio utterance verification for digit strings (1990s),
  selective classification, Learn-then-Test (Angelopoulos et al., 2021), confirmation dialogues.

## Layout

```
src/pramaan/   types, lang (per-language settings), normalise, render, confusables, lattice, witness,
               evidence, score, decide, gate, question, executor, bundle, cache, pipeline, sources/, live/
eval/          tune.py (policy, tuning speakers only), run_eval.py (all arms, test speakers), analysis.py
               (baselines at matched budgets, slices, cost), g2.py (witness gate)
scripts/       gen_prompts, gen_clips, gen_fresh (locked set), gen_te (Telugu), gen_human_prompts,
               gen_human_extras, collect, build_evidence, measure_questions, measure_extras, strong_baseline,
               fresh_mic, fetch_model, selfcheck
data/          prompts, manifest, splits, cache.sqlite (raw responses), evidence.jsonl, policy.json
results/       every published table and the JSON behind it
demo/          the recorded calls the hosted demos play
tests/         unit and property tests, all offline
ui/            live call, evidence and results views
g0/            the first probe: prompts and results that eval/g2.py and one test still read
main.py        hosted entrypoint (Vercel), replay mode only
```
