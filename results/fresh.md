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
