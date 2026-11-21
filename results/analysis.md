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
