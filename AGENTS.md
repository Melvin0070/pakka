# Pramaan (प्रमाण): a voice agent may not act on a number it cannot prove it heard

**Live, no login, nothing to install:**

- Hindi and Hinglish: https://pramaan-voice.vercel.app
- Telugu: https://pramaan-voice-te.vercel.app

**Runs locally with no API key, no account and no network after setup** (about 3 minutes, 481 MB download):

```
make setup          # install, then download the open acoustic model
make demo-offline   # http://127.0.0.1:8765
make play           # in a second terminal: plays all four recorded calls and prints both sides
```

Equal AI Builders hackathon, challenge 2 (Voice AI for India). Built solo at the event.

## What this is, in one minute

**The problem.** A speech-to-speech model goes from sound straight to a tool call. Nothing in between can be
checked. On Indian phone calls it mishears exactly the things that cost money: "सवा दो लाख" (₹2,25,000) logged
as ₹2,00,000, "తొంభై వేలు" (₹90,000) logged as ₹9,000, one digit of a callback number, an amount dropped
entirely. The agent then confirms confidently and the wrong value is in the system of record. On our
phone-grade test calls `gpt-realtime-2.1` alone acted on a wrong amount, date or phone number in 29.5% to
38.6% of calls, and still 18.2% with a prompt written specifically for Indian numbers.

**What Pramaan does.** It sits at the commit point. Every tool call that carries an amount, date, phone
number, PIN code or account number is held for at most 1.2 seconds while independent evidence about the same
audio is gathered. Then one pure function decides:

- **PASS**: independent recogniser families support the value. It executes.
- **REPAIR**: they support a different value. The corrected value executes.
- **ASK**: they are split. The caller gets one short question about the one digit or value in doubt.
- **BLOCK**: no support. Nothing executes.

**The result**, same recordings, same frozen policy (`50d83054eef1`), 8 held-out speakers:

| Test set (220 calls each) | Model alone, wrong and acted on | With Pramaan, wrong | With Pramaan, caller asked |
|---|---|---|---|
| Hindi/Hinglish, locked set 2, number-specific agent prompt | 18.2% | **0.5%** | 4.5% |
| Hindi/Hinglish, locked set 2, generic agent prompt | 29.5% | **0.9%** | 5.9% |
| Hindi/Hinglish, locked set 1 | 38.6% | **1.4%** | 1.8% |
| Telugu, policy untouched from Hindi | 38.6% | **3.2%** | 7.7% |
| PIN codes and account numbers | 35.5% | **1.4%** | 24.1% |

Of the 176 wrong values the model produced on the first 550-call test set, 146 were repaired to the true
value with no question, 21 led to a question, 9 got through. Every number above is reprinted by `make eval`
from committed evidence, with no key and no network. Speakers are synthetic; see
[What is simulated](#what-is-simulated-mocked-or-not-finished).

**Why it is hard, and what was built to solve it** (all in `src/pramaan/`, about 7,000 lines, 695 tests):

| Piece | What it does | File |
|---|---|---|
| Speculative fan-out with a deadline quorum | At end of turn, five recogniser calls from three vendors and a local acoustic model start on the caller's audio before the model has even proposed a tool call. Anything later than tool call + 1.2 s is dropped, live and in the offline scoring alike, so reported numbers are for the system as deployed | `pipeline.py`, `evidence.py` |
| Typed number normaliser | Hand-written inverse text normalisation for Hindi, Hinglish, Telugu and English in three scripts: सवा, साढ़े, पौने, डेढ़, ढाई, "pachpan sau", lakh and crore, double and triple digits, Telugu suffix fractions (రెండున్నర వేలు). "paune teen hazaar", "पौने तीन हज़ार" and "2,750" become the same typed value | `normalise.py`, `lexicon.py` |
| Value lattice | Support is counted per model family, never per model, so two OpenAI transcribers agreeing is one vote. Phone numbers are aligned into a 10-slot confusion network by a weighted edit-distance dynamic programme that also names the contested digit | `lattice.py` |
| Acoustic witness | An open AI4Bharat IndicConformer CTC model runs on the CPU. For each candidate value an exact CTC forward pass scores a graph of every way that value can be spoken, in the same sentence context, written in numpy. The score is a likelihood ratio against the best rival, including confusable values nobody transcribed (उनतालीस / उनचास, thirteen / thirty, a dropped digit). No torch, no alignment library | `witness.py`, `confusables.py`, `render.py` |
| Decision | A pure function of evidence and a frozen, hashed policy. The live server and the offline evaluation call the same function | `decide.py` |
| Risk certificate | Policy chosen on 4 tuning speakers only, frozen with a hash, then one exact Clopper-Pearson bound on 8 held-out speakers: at 95% confidence at most 3.0% to 3.5% of the actions Pramaan lets through are wrong on the Hindi sets | `gate.py`, `eval/tune.py` |
| At-most-once executor | The guard is the only tool runner. Rows are unique per business operation and entity version, so barge-in, retries and regenerated tool calls cannot execute twice, and a caller correction voids outstanding confirmations | `executor.py`, `live/ledger.py` |
| Evidence bundles | Every decision is stored as canonical JSON, content-addressed and hash-chained. `replay()` re-derives a stored decision and fails on any difference | `bundle.py` |
| One-question loop | The question names the single digit or the two candidate values, in Hindi or Telugu. Short answers ("saat", "doosra wala") count only when two independent families agree | `question.py`, `live/session.py` |
| Second language as a swap | Telugu is a lexicon, a renderer and a different acoustic model. Lattice, decision rule and policy are unchanged | `lang.py` |

Pramaan uses no model internals, so it wraps any speech-to-speech stack. Recogniser cost is about $1.92 per
1,000 checked actions; the added hold in live runs was about 350 ms at the median.

## The brief, and where each answer can be checked

The challenge reads: *"India is a voice country. Beyond the model, there is so much to invent in the
harness. Show us: the same recordings on a base model and on your system."* Pramaan is that, literally:
it changes nothing in the model, and every screen and table puts the same recording through the base model
and through the harness side by side.

Each row below is a claim a reviewer may want to test, with the fastest way to test it. All but the last two
need no key.

| What to judge | What we claim | Check it in under a minute |
|---|---|---|
| Fit to the brief | Same recordings, base model against our system, at every touch point | `make play`: each call prints "WITHOUT PRAMAAN executed" and "WITH PRAMAAN executed" for one recording. Web UI: the two panes |
| Is the problem real | The base model acts on wrong money amounts, dates and phone numbers on about a third of phone-grade Indian calls, and still 18.2% with a number-specific prompt | Arm A in `results/headline.json`, `results/fresh2.json`, `results/strong_baseline.json`. Raw model responses are in `data/cache.sqlite` |
| Does it work end to end | Sound in, checked action out, with repair, a question loop, an at-most-once ledger and an audit record | Journeys 1 to 4 below; `tests/test_live.py`, `tests/test_executor.py` |
| Measured improvement | 29.5% wrong to 0.9% on the cleanest locked set, asking on 5.9% of calls | `make eval`, about 15 s, deterministic. CI fails if a published table differs from the committed evidence |
| Is the comparison fair | Nine arms on the same calls, plus a rerun with a stronger agent prompt: three transcribe-then-fill pipelines, two "ask when models disagree" baselines and read-back-everything. The baseline we do not beat on errors is in the table | Results tab; `README.md` "Where it wins, ties and loses" |
| Technical depth | Exact CTC forward scoring of candidate values in numpy, a digit confusion network, a typed multilingual number grammar, a deadline quorum, a frozen policy with an exact binomial certificate | The table above, with one file per piece; `tests/test_witness.py`, `tests/test_lattice.py`, `tests/test_gate.py` |
| Does each part earn its place | An ablation removes every stage in turn, and says where a stage did not help | Ablation rows in `README.md`; "With one part removed" on the Results tab |
| Built for India | Hindi, Hinglish, Telugu and Indian English; lakh and crore; सवा, डेढ़, ढाई, पौने; "double nine"; 8 kHz phone channel with noise; Sarvam and AI4Bharat models in the loop | `tests/test_normalise.py`, `tests/test_telugu.py`; the Telugu demo |
| Does it generalise | Telugu was added by swapping a lexicon and an acoustic model, and scored on the policy frozen on Hindi: 38.6% wrong to 3.2% | `make demo-offline-te`, `make play PORT=8766`; `results/te.md` |
| Use of OpenAI | `gpt-realtime-2.1` is the agent being guarded and the base arm; `gpt-transcribe` and `gpt-4o-transcribe` are evidence sources; OpenAI text-to-speech generated the test speakers | `src/pramaan/sources/`, `src/pramaan/live/server.py` |
| Could it ship | No GPU. Each action costs about $0.002 to check. It degrades gently when a vendor is down. No double execution under barge-in or retries. Every decision can be replayed from its record | Cost, latency and vendor-outage tables in `results/analysis.md`; `bundle.py` |
| Engineering quality | 695 offline tests including property tests, typed, linted, CI on every push | `make check && make test` |
| Honesty | Synthetic speakers, a tied baseline, optimistic bounds and unfinished parts are stated, not hidden | "What is simulated, mocked or not finished" below; "Limits" in `README.md` |
| Live behaviour | The same checks on speech nobody recorded in advance | "Use your voice" on the hosted URLs (journey 5); `results/fresh_input.md` |
| Real callers | Not shown yet. One recorded person; the recorder and scoring for more are built | `/record.html` (journey 6); `results/human_pilot.md` |

## Prerequisites

| Need | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.5 or newer (built with 0.12.1) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | 3.12 exactly (`>=3.12,<3.13`) | uv downloads it by itself during `make setup` |
| make, git, curl | any | |
| Disk | about 1 GB (Hindi), 1.5 GB with Telugu | acoustic model 481 MB per language, virtualenv about 280 MB |
| Browser | Chrome or any Chromium | only for the UI; `make play` needs none |

Not needed: a GPU, Docker, Node, a database server, a message queue, background workers, or any account.
Storage is SQLite files committed in `data/`. Built and run on macOS arm64; lint, tests and `make eval` also pass on Ubuntu x86_64 in GitHub Actions.

## Environment variables

**None are required for the keyless path** (`make test`, `make eval`, `make demo-offline`,
`make demo-offline-te`, `make play`). For live calls copy `.env.example` to `.env`; the Makefile loads it.

| Variable | Needed for | Default |
|---|---|---|
| `OPENAI_API_KEY` | Live calls only: `gpt-realtime-2.1` (the agent), `gpt-transcribe`, `gpt-4o-transcribe` | none |
| `SARVAM_API_KEY` | Optional live evidence source (Sarvam `saaras:v3`) | off |
| `VERBX_API_KEY` | Optional live evidence source (VerbX Vocaline) | off |
| `ELEVENLABS_API_KEY` | Optional. Scribe adapter is wired but was never run | off |
| `PRAMAAN_OFFLINE` | `1` = keyless replay mode. `make demo-offline` sets it | unset |
| `PRAMAAN_LANG` | `hi` or `te`: recogniser settings, acoustic model, questions, demo calls | `hi` |
| `PRAMAAN_REALTIME_MODEL` | Realtime model id | `gpt-realtime-2.1` |
| `PRAMAAN_VOICE` | The agent's speaking voice in live calls | `marin` |
| `PRAMAAN_CACHE` | Recogniser response cache. `make serve` points it at a throwaway copy | `data/cache.sqlite` |
| `PRAMAAN_MODELS` | Where acoustic models are downloaded | `models/` |
| `PRAMAAN_STATE` | Where evidence bundles and the acoustic cache are written | `data/` |
| `SARVAM_MODEL`, `SCRIBE_MODEL` | Vendor model ids | `saaras:v3`, `scribe_v1` |
| `PRAMAAN_HOSTED_LIVE` | Hosting only (`main.py`): `1` lets a public deployment spend the keys | unset |

**No test key is committed.** The repository is public, so a key in it would be scraped. Two things replace
it: the keyless replay mode below, and the two hosted URLs at the top, which run live on the author's keys
with the microphone on.

### What keyless replay mode is

`PRAMAAN_OFFLINE=1` replaces only the paid network calls. For each recorded call, `gpt-realtime-2.1`'s tool
call and each recogniser's transcript are read from the committed cache (`data/cache.sqlite`), exactly as
those models returned them, with their recorded latencies. Everything Pramaan itself does runs for real on
every play: the acoustic model on the CPU, the normaliser, the lattice, the CTC scoring, the decision, the
ledger and the evidence bundle. It is deterministic. Its limits: recorded calls only (the microphone is
disabled and labelled "Your voice needs the network"), the agent's reply is text with no voice, and a call
that ends in a question stops at the question.

## Install, seed, start

There is nothing to seed. The test recordings' evidence, the frozen policy and the recogniser caches are
committed. There is one process (a FastAPI server that also serves the front end) and no workers.

```
git clone https://github.com/Melvin0070/pramaan-voice.git && cd pramaan-voice
make setup            # uv sync + download the Hindi acoustic model (481 MB, Hugging Face, no login)
make test             # 695 passed, 1 skipped, about 10 s, offline
make eval             # about 15 s, offline: reprints every results table from committed evidence
```

Then start one or both servers. Each command stays in the foreground; use one terminal per server.

| Command | URL | Keys | What runs |
|---|---|---|---|
| `make demo-offline` | http://127.0.0.1:8765 | none | Hindi/Hinglish, keyless replay |
| `make demo-offline-te` | http://127.0.0.1:8766 | none | Telugu, keyless replay. Downloads the Telugu model (481 MB) on first run |
| `make serve` | http://127.0.0.1:8765 | `OPENAI_API_KEY` | Hindi/Hinglish, live models, microphone, recorder |
| `make serve-te` | http://127.0.0.1:8766 | `OPENAI_API_KEY` | Telugu, live models. Run `uv run python scripts/fetch_model.py te` once first |
| `make demo` | http://127.0.0.1:8765 | `OPENAI_API_KEY` | Preflight check of key, model and files, then `make serve` |

`PORT=9000 make demo-offline` (or `make serve`) moves the Hindi server. The server binds to 127.0.0.1.

Health check: `curl -s http://127.0.0.1:8765/api/health`. A correct keyless start returns
`"offline": true, "guard": "pipeline", "witness_files": true, "policy_hash": "50d83054eef1"`.
If `witness_files` is `false` the acoustic model is missing and every action will be held or blocked:
run `make setup` again.

Other endpoints: `/api/scenarios` (the recorded calls), `/api/results?set=synthetic|fresh|fresh2|te|strong`,
`/api/analysis`, `/api/clips`, WebSocket `/ws?replay=<call_id>` (events as JSON).

## Logins

**There are none.** No accounts, passwords, roles or sessions exist anywhere in the product, so there are no
test logins to hand out. The three ways in:

| Who | Touch point | Identification |
|---|---|---|
| Anyone evaluating the guard | Web UI at `/` (hosted or local), or `make play` in a terminal | none |
| A caller speaking live | "Use your voice" on the web UI (hosted URLs, or `make serve`) | none |
| A study participant recording test audio | `/record.html`, local `make serve` only | a self-chosen code such as `p01`, no password |

## Journeys to try

### 1. Terminal, no browser, no key (2 minutes)

With `make demo-offline` running:

```
make play                      # all four recorded Hindi calls
make play CALL=one_question    # one call
make play PORT=8766            # the Telugu calls, with make demo-offline-te running
```

For each call it prints what the caller said, the true value, what the model alone executed, what each
recogniser heard and how fast, the decision, and what Pramaan executed. Expected in keyless mode:

| Call id | Caller said | Model alone executes | Pramaan executes |
|---|---|---|---|
| `amount_dropped` | डेढ़ लाख का cheque वीरवार को मिलेगा | Thursday, **no amount** | ₹1,50,000 and Thursday (REPAIR: restored the dropped value) |
| `phone_digit` | ...सात एक, डबल सेवन डबल एट, आठ सात एक सात | **8**177888717 | 7177888717 (REPAIR) |
| `one_question` | callback number है सिक्स फ़ाइव एट नाइन, ज़ीरो एक तीन, टू फ़ोर फ़ाइव | 65890**82**345 | nothing yet. ASK: "Aakhri se paanchvaan ank ek hai ya aath?" (is the fifth digit from the end one or eight?) |
| `amount_misheard` | अभी सवा दो लाख भेज रहा हूँ, बाकी तीस तारीख को | **₹2,00,000**, 30th | ₹2,25,000, 30th (REPAIR) |
| `te_ninety_thousand` | ...తొంభై వేల రూపాయల గురించి | **₹9,000** | ₹90,000 (REPAIR) |
| `te_eight_and_a_half_lakh` | ఎనిమిదిన్నర లక్షల రూపాయలు COD | **₹1,00,000** | ₹8,50,000 (REPAIR) |
| `te_phone_digits` | callback number ఆరు ఏడు ఆరు ఎనిమిది, డబుల్ ఆరు జీరో, ఏడు జీరో ఆరు | **98786600706** (11 digits) | 6768660706 (REPAIR) |
| `te_dropped_twenty` | ...ఇరవై రెండు వేల ఐదు వందల రూపాయల గురించి | **₹2,500** | ₹22,500 (REPAIR) |

### 2. Web UI, Demo tab (3 minutes; hosted URL or local)

1. Open the URL. The chip at the top right reads "Offline replay of recorded model answers" in keyless
   mode, or shows the live model when keys are present. A banner reading "Scripted checks" must **not**
   appear; if it does, the evidence pipeline failed to load.
2. The scoreboard at the top shows the measured before and after across the recorded test calls. Its
   toggle switches which baseline Pramaan is compared against.
3. Under "Recorded calls" click **An amount the agent left out**. The caller's words appear and the audio
   plays. Left pane, "Without Pramaan": the slip shows Thursday and an empty amount. Right pane, "With
   Pramaan": the stamp shows the call held, then the slip fills with ₹1,50,000 and Thursday, and "Checked
   against" lists each recogniser and what it heard.
4. Click **Evidence is split, so it asks**. The right pane shows the agent's question about one digit.
   With live models (hosted URL or `make serve`) the recorded answer then plays and the right number,
   65890 13245, is committed. In keyless mode the call stops at the question.
5. Click **A Hindi fraction, misheard**: left ₹2,00,000, right ₹2,25,000.
6. Click **One digit of a phone number**: the contested digit is marked.
7. "Play any other recorded call" lists more clip ids. In a fresh clone only the demo calls have audio
   (the full test audio is not in the repository), so use the four cards.

On the hosted URLs and under `make serve` these calls run through the real models each time. The realtime
model is not deterministic, so the left pane can differ between plays (the fraction came out as ₹2,00,000
three times and ₹2,12,500 twice in five runs; the phone digit is misheard about one time in five). The text
on each card is a typical result; the panes show what actually happened.

### 3. Web UI, Evidence tab

After playing any call, open **Evidence**. It shows why the action was held: what each recogniser heard,
when each answer arrived against the 1.2 s deadline, and the ledger transitions for that action
(proposed, held, then committed, asked or blocked).

### 4. Web UI, Results tab

**Results** shows every arm on the same calls, with a toggle for each set (synthetic voices, locked set 1,
locked set 2, Telugu, strong prompt): the model alone, three transcribe-then-fill pipelines, two
"ask when two models disagree" baselines, read-everything-back, and Pramaan. Below it: the ablation table
(each stage removed in turn), what happened to the model's wrong values, the comparison against the
strongest simple baseline at matched question budgets, slices by language and noise, and what happens when
a vendor is down. The same tables are in `README.md` and `results/`.

### 5. Your own voice (hosted URLs, or `make serve` with a key)

1. Open https://pramaan-voice.vercel.app in Chrome, with a headset if possible.
2. Click **Use your voice** and allow the microphone.
3. Say an amount and a day in Hindi or Hinglish, for example "पौने तीन हज़ार रुपये शुक्रवार को दूँगा" or
   "ढाई लाख, pandrah tareekh ko". Or dictate a 10-digit number: "mera number note karo, nine eight double
   four, seven one, three zero, five six".
4. Both panes fill from the same realtime session: the left shows the model's own tool call, the right
   the held and checked one. If the evidence is split the agent asks one question aloud; answer it.
5. Most calls are heard correctly, and then both panes agree. That is expected.

A browser without a real microphone cannot do this journey; use the recorded calls.

### 6. Recording a test speaker (local, key required)

`make serve`, then http://127.0.0.1:8765/record.html. Enter a code such as `p01`, tick the consent box,
press Begin, and read the lines shown. Clips are passed through the phone channel on the server and written
under `data/human/`. `make human` then scores them once on the frozen policy into `results/human.md`. The
recorder is disabled in keyless mode and on the hosted URLs because it writes to disk.

### 7. Reproducing the numbers (no key)

`make eval` rescoring is deterministic. CI (`.github/workflows/ci.yml`) fails if the tables in `README.md`
and `results/*.md` differ from what the committed evidence produces. `make check` runs ruff and pyright.

## What is simulated, mocked or not finished

Simulated or mocked:

- **Test speakers are synthetic.** OpenAI text-to-speech voices with varied speaking instructions, passed
  through a simulated 8 kHz AMR-NB and A-law phone channel, part with babble noise. One human (the author,
  15 clips) has been recorded and is kept out of the headline numbers: `results/human_pilot.md`.
- **The system of record is an in-memory list.** The tool call the agent makes (`log_commitment`) appends
  to a list in the server process. No payment, CRM or ledger system is connected.
- **Keyless mode replays recorded model output**, as described above. The recognisers and the realtime
  model are not called.
- **Answers in the measured question loop are synthetic and cooperative** (the same voice states the true
  value).
- **If the evidence pipeline cannot load**, the server falls back to scripted checks and says so in a banner
  and in `/api/health` (`"guard": "fake"`). This should never appear after `make setup`.

Not finished, and not claimed:

- No real callers, real handsets or real phone lines have been tested. Telephony (SIP, a phone number) is
  not connected; the caller is a browser microphone or a recording.
- The full synthetic test audio (about 2,600 clips) is not in the repository; the evidence derived from it
  is. `make eval` needs only the evidence. Regenerating the clips needs a key and spends credits.
- `make digits`, `make strong-baseline`, `make human` and `eval/g2.py` need those clips or new recordings.
  Their stored results are in `results/`.
- Asking only when `gpt-transcribe` and Sarvam disagree is a strong, much simpler baseline. Pramaan does
  **not** beat it on errors (the difference is within noise). Its measured advantage is fewer questions on
  every Hindi set (for example 4 against 15 on locked set 1), gentler behaviour when a vendor is down, and
  that it corrects the speech-to-speech model in place instead of replacing it with a transcript pipeline.
- The first test set and locked set 1 were scored more than once during the build, so their bounds are
  optimistic. Locked set 2 was scored once after the last fix.
- Telugu has no tuned policy of its own, no second locked set and no human recordings. Its bound is 6.4%,
  above the 5% the policy was frozen for.
- PIN codes and account numbers are recognised only directly after a spoken label, which is why Pramaan
  asks on 24.1% of those calls.
- One language per server process. A call that switches between Hindi and Telugu is not routed.
- The ElevenLabs Scribe adapter has never been run. VerbX Vocaline's model lineage is undocumented and it
  is counted as its own family on that assumption.
- A live call with only `OPENAI_API_KEY` set (no Sarvam or VerbX key) has not been measured. The closest
  figure is the "OpenAI transcribers only" ablation row in `README.md`, which lets more errors through.
- No authentication, rate limiting or multi-tenant separation. The hosted demos are open and may be
  switched back to keyless replay at any time to protect the keys.

More detail: `README.md` (full tables, ablations, limits, prior art), `NOTE.md` (built, reused, simulated),
`DEMO.md` (two-minute run of show).

## Repository map

```
src/pramaan/        the guard: normalise, lattice, witness, decide, gate, executor, bundle, question
src/pramaan/live/   FastAPI server, call session, ledger, keyless replay, recorder
src/pramaan/sources recogniser adapters: OpenAI, Sarvam, VerbX, ElevenLabs, realtime agent
ui/                 the front end (static, served by the same server): index.html, record.html
eval/               policy tuning, every baseline arm, analysis
scripts/            data generation, collection, play_call.py, fetch_model.py, selfcheck.py
data/               prompts, speaker split, frozen policy, recogniser caches, evidence
results/            every published table and the JSON behind it
demo/               the eight recorded calls and their descriptions
tests/              695 unit and property tests, all offline
main.py             hosted entrypoint (Vercel)
```

## For coding agents working in this repository

- Before finishing a change: `make check && make test && make eval`, and confirm `git diff` shows no change
  to `README.md` or `results/*.md` unless the change was meant to move a number.
- `data/policy.json`, `data/splits.json` and `data/cache.sqlite` are the evidence behind the published
  numbers. Do not edit them. Live calls write to `data/cache.live.sqlite`, a throwaway copy.
- `decide.py` must stay pure: no network, clock, randomness or environment.
- Do not tune anything on the test speakers. `eval/tune.py` reads tuning speakers only.
- Commits follow Conventional Commits: `type(scope): imperative subject`.
