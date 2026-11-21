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
