"""Download the Hindi CTC acoustic model (MIT, ungated ONNX export of AI4Bharat IndicConformer) to models/hi.

Usage: uv run python scripts/fetch_model.py [--int8]
"""

import pathlib
import sys

import httpx

REPO = "https://huggingface.co/OpenVoiceOS/ai4bharat-indicconformer-hi-onnx/resolve/main"
DEST = pathlib.Path(__file__).resolve().parent.parent / "models" / "hi"
FP32 = ("config.json", "vocab.txt", "model.onnx", "model.onnx_data")
INT8 = ("model.int8.onnx",)


def fetch(name: str) -> None:
    out = DEST / name
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        size = int(client.head(f"{REPO}/{name}").headers.get("content-length", 0))
        if out.exists() and size and out.stat().st_size == size:
            print(f"ok       {name}")
            return
        tmp = out.with_suffix(out.suffix + ".part")
        with client.stream("GET", f"{REPO}/{name}") as r, open(tmp, "wb") as f:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        tmp.replace(out)
        print(f"fetched  {name} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    for n in FP32 + (INT8 if "--int8" in sys.argv else ()):
        fetch(n)
