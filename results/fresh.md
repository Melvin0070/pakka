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
