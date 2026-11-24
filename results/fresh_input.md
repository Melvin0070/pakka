# Fresh input through the live microphone path

Run on 2026-11-22 on policy `50d83054eef1`. Twelve new Hindi and Hinglish sentences, with expected values written
before the run, were spoken by the macOS Lekha voice and streamed in real time to the same WebSocket the browser
microphone uses. None of the audio was in the replay cache, so every recogniser and both realtime agents ran live.

| Result | Realtime model alone | With Pakka |
|---|---|---|
| Right value acted on | 7 of 12 | 8 of 12 |
| Wrong value acted on | 5 of 12 | 0 of 12 |
| Held, caller asked one question | 0 of 12 | 4 of 12 |

| Caller said | Truth | Model alone | Pakka |
|---|---|---|---|
| बारह हज़ार पाँच सौ, शुक्रवार | ₹12,500, Friday | right | committed, right |
| साढ़े चार हज़ार, सत्रह तारीख | ₹4,500, 17th | right | committed, right |
| पौने दो लाख, सोमवार | ₹1,75,000, Monday | **₹2,00,000** | asked: 2,00,000 or 1,75,000 |
| नौ चार आठ तीन, सात दो, छह एक पाँच शून्य | 9483726150 | right | committed, right |
| ढाई हज़ार, मंगलवार | ₹2,500, Tuesday | **₹2,000** | asked: 1,000 or 2,500 |
| उनचास हज़ार, इक्कीस तारीख | ₹49,000, 21st | right | committed, right |
| सवा तीन लाख, बुधवार | ₹3,25,000, Wednesday | right | committed, right |
| छत्तीस सौ, पच्चीस तारीख | ₹3,600, 25th | right | committed, right |
| आठ दो, छह छह, सात एक, नौ तीन, पाँच चार | 8266719354 | right | committed, right |
| डेढ़ हज़ार, रविवार | ₹1,500, Sunday | **₹1,000** | asked: 1,500 or 1,000 |
| तिरेसठ हज़ार, शनिवार | ₹63,000, Saturday | **₹30,000** | committed, right |
| अठहत्तर सौ, दस तारीख | ₹7,800, 10th | **₹1,500** | asked: 100 or 7,800 |

Limits:

- This is one synthetic voice and 12 sentences, so it shows the system runs on new input. It is not an accuracy estimate.
- The four questions were not answered in this run, so those calls stopped at the question. Each question did offer the true value.
- The answer path was exercised separately on the recorded "Evidence is split" call, which committed the right number in 3 of 3 runs.
- No human spoke into a physical microphone for this test.
