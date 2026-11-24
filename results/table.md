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
| **Pakka** (P) | 9 (1.6%) | 31 (5.6%) | 21 | 519 |

Certificate: of 519 actions Pakka let through, 9 were wrong; one-sided 95% Clopper-Pearson upper bound 3.0%. Speaker-level: 6 of 8 speakers had any silent error (bound 95.4%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pakka as frozen | 9 | 31 | 21 |
| without the acoustic model | 10 | 45 | 26 |
| OpenAI transcribers only | 35 | 13 | 9 |
| acoustic model as the only check | 14 | 25 | 15 |
| without the language check (acoustic model also judges English) | 9 | 77 | 21 |
| without Sarvam | 11 | 97 | 23 |
| without the dropped-value check | 18 | 31 | 21 |
| no deadline (wait for every source) | 9 | 34 | 22 |
| deadline 300 ms | 9 | 31 | 21 |
