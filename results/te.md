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
