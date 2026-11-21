import json, pathlib, subprocess

HERE = pathlib.Path(__file__).parent
CLIPS = HERE / "clips"
PROMPTS = json.loads((HERE / "prompts.json").read_text())
FIELDS = ["amount_rupees", "day_of_month", "weekday", "phone"]

TOOL = {
    "type": "function",
    "name": "log_commitment",
    "description": "Record what the caller committed to on this call. Fill only the values the caller actually said.",
    "parameters": {
        "type": "object",
        "properties": {
            "amount_rupees": {"type": ["integer", "null"], "description": "Amount in rupees as a plain integer."},
            "day_of_month": {"type": ["integer", "null"], "description": "Day of the month (1-31) if the caller gave a date."},
            "weekday": {"type": ["string", "null"],
                        "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", None]},
            "phone": {"type": ["string", "null"], "description": "10-digit Indian mobile number, digits only."},
        },
        "required": FIELDS,
    },
}
INSTRUCTIONS = ("You are an assistant answering a phone call in India. Callers speak Hindi, English or a mix. "
                "When the caller states an amount, a date or a phone number, call log_commitment with those values.")


def phone_grade(src, dst):
    # 8 kHz mu-law round trip, then back to 24 kHz PCM: approximates a narrowband phone leg.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", "8000", "-ac", "1",
                    "-c:a", "pcm_mulaw", "-f", "wav", "/dev/stdout"], check=True, stdout=open(dst.with_suffix(".ulaw.wav"), "wb"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(dst.with_suffix(".ulaw.wav")),
                    "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)], check=True)
    dst.with_suffix(".ulaw.wav").unlink()


def norm(field, v):
    if v in (None, "", "null"):
        return None
    if field == "phone":
        d = "".join(c for c in str(v) if c.isdigit())
        return d[-10:] if len(d) >= 10 else d
    if field == "weekday":
        return str(v).strip().lower()
    try:
        return int(v)
    except (TypeError, ValueError):
        return v
