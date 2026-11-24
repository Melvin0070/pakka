"""Caller audio on a sample clock that matches the Realtime session's audio_start_ms/audio_end_ms."""

from __future__ import annotations

import hashlib

RATE = 24000
BYTES_PER_MS = RATE * 2 // 1000


class RingBuffer:
    def __init__(self, seconds: float = 180.0) -> None:
        self._cap = int(seconds * 1000) * BYTES_PER_MS
        self._buf = bytearray()
        self._dropped = 0  # bytes trimmed from the front

    def append(self, pcm: bytes) -> None:
        self._buf += pcm
        extra = len(self._buf) - self._cap
        if extra > 0:
            extra -= extra % 2
            del self._buf[:extra]
            self._dropped += extra

    @property
    def total_ms(self) -> float:
        return (self._dropped + len(self._buf)) / BYTES_PER_MS

    def slice_ms(self, start_ms: float, end_ms: float) -> bytes:
        lo = max(int(start_ms) * BYTES_PER_MS - self._dropped, 0)
        hi = min(max(int(end_ms) * BYTES_PER_MS - self._dropped, 0), len(self._buf))
        return bytes(self._buf[lo:hi]) if hi > lo else b""


def audio_sha(pcm: bytes) -> str:
    return hashlib.sha256(pcm).hexdigest()
