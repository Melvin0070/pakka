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
