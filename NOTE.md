# What is built, reused and simulated

## Built for this project
- The action guard: holding a tool call, the decision rule, repair, the one-question loop and the at-most-once ledger.
- The typed Hindi, Hinglish and English number normaliser, the value lattice and the phone digit alignment.
- CTC scoring of candidate values on top of the acoustic model's output.
- The evaluation harness, baselines, policy tuning, risk bound, evidence bundles and the demo UI.

## Reused
- OpenAI `gpt-realtime-2.1`, `gpt-transcribe`, `gpt-4o-transcribe` and text-to-speech, through their APIs.
- Sarvam `saaras:v3` and VerbX Vocaline speech-to-text, through their APIs.
- The open AI4Bharat IndicConformer Hindi model, in the OpenVoiceOS ONNX export.
- Open-source libraries listed in `pyproject.toml`.

## Simulated
- Test speakers are synthetic: OpenAI text-to-speech voices through a simulated 8 kHz phone channel, part with added noise.
- The fresh-input run in `results/fresh_input.md` uses the macOS Lekha voice streamed over the microphone WebSocket.
- The CRM that receives actions is an in-memory list. No real payment, ledger or customer system is connected.
- Answers in the measured question loop are synthetic and cooperative.

## Not shown
- Real callers and real phone lines. One person (15 clips) has been recorded, which is too few to rank methods.
- Pramaan does not beat the simple "ask when OpenAI and Sarvam disagree" baseline on errors. Its measured advantage is fewer questions on most sets.

## Data
All audio is synthetic or recorded by the author. No customer or third-party call data is used.
