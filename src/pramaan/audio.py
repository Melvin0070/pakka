"""PCM16 mono wav helpers and phone-channel simulators."""

from __future__ import annotations

import io
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import soxr

from .types import sha256_hex

RATE = 24_000


def read_wav(path: Path | str) -> tuple[bytes, int]:
    with wave.open(str(path)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: need PCM16 mono, got {w.getnchannels()}ch {w.getsampwidth() * 8}bit")
        return w.readframes(w.getnframes()), w.getframerate()


def read_pcm24k(path: Path | str) -> bytes:
    pcm, rate = read_wav(path)
    return pcm if rate == RATE else resample(pcm, rate, RATE)


def wav_bytes(pcm: bytes, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def write_wav(path: Path | str, pcm: bytes, rate: int = RATE) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_bytes(wav_bytes(pcm, rate))
    tmp.replace(path)  # atomic, so a killed generator never leaves a truncated clip that looks done


def sha(pcm: bytes) -> str:
    return sha256_hex(pcm)


def to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def to_pcm(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()


def resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    if src_rate == dst_rate:
        return pcm
    return to_pcm(soxr.resample(to_float(pcm), src_rate, dst_rate, quality="HQ"))


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *args], check=True)


def phone_amr(src: Path | str, dst: Path | str) -> None:
    """8 kHz AMR-NB 12.2k encode/decode, then an A-law round trip (the PSTN leg), back to 24 kHz PCM16."""
    with tempfile.TemporaryDirectory() as td:
        amr, alaw = Path(td) / "x.amr", Path(td) / "x_alaw.wav"
        _ffmpeg(
            "-i", str(src), "-ar", "8000", "-ac", "1", "-c:a", "libopencore_amrnb", "-b:a", "12.2k", str(amr)
        )
        _ffmpeg("-i", str(amr), "-ar", "8000", "-ac", "1", "-c:a", "pcm_alaw", str(alaw))
        out = Path(td) / "out.wav"
        _ffmpeg("-i", str(alaw), "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", str(out))
        pcm, _ = read_wav(out)
    write_wav(dst, pcm)


def white_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.standard_normal(n).astype(np.float32)


def babble(n: int, talkers: list[np.ndarray], rng: np.random.Generator, k: int = 6) -> np.ndarray:
    """Sum of k other-speaker clips at random offsets, looped to length n."""
    out = np.zeros(n, dtype=np.float32)
    for i in rng.choice(len(talkers), size=min(k, len(talkers)), replace=False):
        t = talkers[int(i)]
        t = t / (np.sqrt(np.mean(t**2)) + 1e-9)
        tiled = np.tile(t, n // len(t) + 2)
        off = int(rng.integers(0, len(t)))
        out += tiled[off : off + n]
    return out


def add_noise(pcm: bytes, snr_db: float, noise: np.ndarray) -> bytes:
    """Scale `noise` so speech power / noise power = snr_db, measured over the active (non-silent) speech."""
    x = to_float(pcm)
    frame = 480
    nfr = len(x) // frame
    energies = (x[: nfr * frame].reshape(nfr, frame) ** 2).mean(axis=1) if nfr else np.array([np.mean(x**2)])
    active = energies[energies > 0.05 * energies.max()] if energies.size else energies
    p_speech = float(active.mean()) if active.size else float(np.mean(x**2))
    noise = noise[: len(x)]
    p_noise = float(np.mean(noise**2)) + 1e-12
    y = x + noise * np.sqrt(p_speech / (p_noise * 10 ** (snr_db / 10)))
    peak = float(np.abs(y).max())
    if peak > 0.99:
        y = y * (0.99 / peak)
    return to_pcm(y)
