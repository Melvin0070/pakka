"""Download a CTC acoustic model (MIT, ungated ONNX export of AI4Bharat IndicConformer) to models/<lang>.

Usage: uv run python scripts/fetch_model.py [hi te ...] [--int8]     (default: hi)
"""

import os
import pathlib
import sys

import httpx

REPO = "https://huggingface.co/OpenVoiceOS/ai4bharat-indicconformer-{lang}-onnx/resolve/main"
MODELS = pathlib.Path(
    os.environ.get("PAKKA_MODELS") or pathlib.Path(__file__).resolve().parent.parent / "models"
)
FP32 = ("config.json", "vocab.txt", "model.onnx", "model.onnx_data")
INT8 = ("model.int8.onnx",)


def fetch(lang: str, name: str) -> None:
    out = MODELS / lang / name
    url = f"{REPO.format(lang=lang)}/{name}"
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        size = int(client.head(url).headers.get("content-length", 0))
        if out.exists() and size and out.stat().st_size == size:
            print(f"ok       {lang}/{name}")
            return
        tmp = out.with_suffix(out.suffix + ".part")
        with client.stream("GET", url) as r, open(tmp, "wb") as f:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        tmp.replace(out)
        print(f"fetched  {lang}/{name} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    langs = [a for a in sys.argv[1:] if not a.startswith("--")] or ["hi"]
    for lang in langs:
        (MODELS / lang).mkdir(parents=True, exist_ok=True)
        # --int8-only skips the 481 MB full-precision weights.
        names = ("config.json", "vocab.txt", *INT8) if "--int8-only" in sys.argv else FP32
        for n in names + (INT8 if "--int8" in sys.argv else ()):
            fetch(lang, n)
