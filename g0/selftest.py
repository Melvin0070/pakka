"""Pipeline check with synthetic speech, so the recorder is not needed. Not evidence: TTS is far easier than a real caller."""
import subprocess, sys
from openai import OpenAI
from common import CLIPS, PROMPTS, phone_grade

client = OpenAI()
n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
voice = sys.argv[2] if len(sys.argv) > 2 else "alloy"
spk = f"tts{voice}"
for p in PROMPTS[:n]:
    mp3 = CLIPS / f"{spk}_{p['id']}.mp3"
    clean = CLIPS / f"{spk}_{p['id']}_clean.wav"
    if clean.exists():
        continue
    with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts", voice=voice, input=p["say"],
            instructions="Speak in natural Hindi-English as an Indian caller on a phone.") as r:
        r.stream_to_file(mp3)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "24000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(clean)], check=True)
    mp3.unlink()
    phone_grade(clean, CLIPS / f"{spk}_{p['id']}_phone.wav")
print("ok")
