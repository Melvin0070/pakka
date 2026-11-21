"""List the speech and video models this key can call."""

from openai import OpenAI

KEYS = ("tts", "sora", "video", "audio", "realtime", "transcribe", "speech", "live")
for m in sorted(x.id for x in OpenAI().models.list()):
    if any(k in m for k in KEYS):
        print(m)
