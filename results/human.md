15 actions, 1 held-out human speakers, phone-grade audio. Policy `50d83054eef1`.

| Arm | Wrong and acted on | Caller asked | of which the value was wrong | Acted without asking |
|---|---|---|---|---|
| Realtime model alone (A) | 4 (26.7%) | 0 (0.0%) | 0 | 15 |
| Transcribe, then fill the form (B) | 0 (0.0%) | 0 (0.0%) | 0 | 15 |
| Second vendor, then fill the form (V) | 3 (20.0%) | 0 (0.0%) | 0 | 15 |
| Sarvam, then fill the form (S) | 0 (0.0%) | 0 (0.0%) | 0 | 15 |
| Trust one model's confidence (B-LP) | 0 (0.0%) | 15 (100.0%) | 3 | 0 |
| Ask when two models disagree (B-2M) | 0 (0.0%) | 3 (20.0%) | 0 | 12 |
| Ask when OpenAI and Sarvam disagree (B-2S) | 0 (0.0%) | 0 (0.0%) | 0 | 15 |
| Read everything back (A-RB) | 0 (0.0%) | 15 (100.0%) | 4 | 0 |
| **Pramaan** (P) | 0 (0.0%) | 0 (0.0%) | 0 | 15 |

Certificate: of 15 actions Pramaan let through, 0 were wrong; one-sided 95% Clopper-Pearson upper bound 18.1%. Speaker-level: 0 of 1 speakers had any silent error (bound 95.0%). Added hold p50 0 ms, p95 1200 ms.

| Ablation | Wrong and acted on | Caller asked | of which wrong |
|---|---|---|---|
| Pramaan as frozen | 0 | 0 | 0 |
| without the acoustic model | 0 | 0 | 0 |
| OpenAI transcribers only | 0 | 0 | 0 |
| acoustic model as the only check | 0 | 0 | 0 |
| without the language check (acoustic model also judges English) | 0 | 0 | 0 |
| without Sarvam | 0 | 2 | 0 |
| without the dropped-value check | 0 | 0 | 0 |
| no deadline (wait for every source) | 0 | 0 | 0 |
| deadline 300 ms | 0 | 0 | 0 |
