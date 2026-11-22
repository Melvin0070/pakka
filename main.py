"""Hosted entrypoint (Vercel). `make serve` does not use this file.

The host's filesystem is read-only apart from /tmp and the acoustic model is not in the repository, so this
points every write at /tmp, copies the committed response cache there and fetches the model on a cold start.
Without OPENAI_API_KEY the server runs in replay mode: recorded calls only, recogniser answers from the
cache, the acoustic check and the decision computed for real. Nothing here spends API credits.
"""

import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
TMP = pathlib.Path("/tmp/pramaan")
LANG = os.environ.get("PRAMAAN_LANG") or "hi"

sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("PRAMAAN_STATE", str(TMP / "state"))
os.environ.setdefault("PRAMAAN_MODELS", str(TMP / "models"))
if not os.environ.get("OPENAI_API_KEY"):
    os.environ.setdefault("PRAMAAN_OFFLINE", "1")

cache = TMP / "cache.sqlite"
if not cache.exists():
    TMP.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "data" / ("cache.sqlite" if LANG == "hi" else f"{LANG}/cache.sqlite"), cache)
os.environ.setdefault("PRAMAAN_CACHE", str(cache))

if not (TMP / "models" / LANG / "model.onnx_data").exists():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_model.py"), LANG], check=True)

from pramaan.live.server import app  # noqa: E402, F401
