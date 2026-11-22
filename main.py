"""Hosted entrypoint (Vercel). `make serve` does not use this file.

The host's filesystem is read-only apart from /tmp and the acoustic model is not in the repository, so this
points every write at /tmp, copies the committed response cache there and fetches the model on a cold start.
The hosted server always runs in replay mode, whatever keys the project holds: recorded calls only,
recogniser answers from the cache, the acoustic check and the decision computed for real. A public URL with
an open microphone would let anyone spend the owner's API credits, so going live takes PRAMAAN_HOSTED_LIVE=1.
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
if os.environ.get("PRAMAAN_HOSTED_LIVE") != "1" or not os.environ.get("OPENAI_API_KEY"):
    os.environ["PRAMAAN_OFFLINE"] = "1"

cache = TMP / "cache.sqlite"
if not cache.exists():
    TMP.mkdir(parents=True, exist_ok=True)
    # Two cold starts can share /tmp: a half-copied file must never sit at the final name.
    part = TMP / f"cache.{os.getpid()}.part"
    shutil.copy(ROOT / "data" / ("cache.sqlite" if LANG == "hi" else f"{LANG}/cache.sqlite"), part)
    part.replace(cache)
os.environ.setdefault("PRAMAAN_CACHE", str(cache))

if not (TMP / "models" / LANG / "model.onnx_data").exists():
    # Not fatal: without the model the server still starts and /api/health reports the scripted guard.
    fetched = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_model.py"), LANG])
    if fetched.returncode:
        print(f"acoustic model download failed ({fetched.returncode})", file=sys.stderr)

from pramaan.live.server import app  # noqa: E402, F401
