"""Record the G0 clips. Usage: python g0/record.py [speaker] [--mic 1]  (Enter to start, Enter to stop, r to redo, s to skip)"""
import subprocess, sys
from common import CLIPS, PROMPTS, phone_grade

args = [a for a in sys.argv[1:] if not a.startswith("--")]
speaker = args[0] if args else "s1"
mic = sys.argv[sys.argv.index("--mic") + 1] if "--mic" in sys.argv else "1"

for i, p in enumerate(PROMPTS, 1):
    clean = CLIPS / f"{speaker}_{p['id']}_clean.wav"
    if clean.exists():
        continue
    while True:
        print(f"\n[{i}/{len(PROMPTS)}] Say naturally, as on a phone call:\n\n    {p['say']}\n")
        if input("Enter to start (s = skip): ").strip().lower() == "s":
            break
        rec = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", f":{mic}",
                                "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(clean)], stdin=subprocess.PIPE)
        input("  recording... Enter to stop ")
        rec.communicate(b"q")
        if input("Enter to keep (r = redo): ").strip().lower() != "r":
            phone_grade(clean, CLIPS / f"{speaker}_{p['id']}_phone.wav")
            break
        clean.unlink(missing_ok=True)
print("\nDone. Now run: python g0/run.py")
