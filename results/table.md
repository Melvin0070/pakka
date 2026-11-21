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
