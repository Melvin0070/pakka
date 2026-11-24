import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pakka import audio
from pakka.live import record


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(record, "HUMAN", tmp_path)
    monkeypatch.setattr(record, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(audio, "phone_amr", lambda src, dst: audio.write_wav(dst, audio.read_pcm24k(src)))
    app = FastAPI()
    app.include_router(record.router)
    return TestClient(app)


def tone(seconds: float, amp: float = 0.3) -> bytes:
    t = np.arange(int(seconds * audio.RATE)) / audio.RATE
    return audio.wav_bytes(audio.to_pcm(amp * np.sin(2 * np.pi * 220 * t).astype(np.float32)))


def test_speakers_get_disjoint_slices_and_resume(client):
    a = client.get("/api/record/prompts", params={"speaker": "p01"}).json()["prompts"]
    assert len(a) == record.PER_SPEAKER
    assert client.post(f"/api/record/p01/{a[0]['id']}", content=tone(2)).status_code == 200
    again = client.get("/api/record/prompts", params={"speaker": "p01"}).json()["prompts"]
    assert [p["id"] for p in again] == [p["id"] for p in a] and again[0]["done"]
    b = client.get("/api/record/prompts", params={"speaker": "p02"}).json()["prompts"]
    assert not {p["id"] for p in a} & {p["id"] for p in b}


def test_rerecord_replaces_and_truth_comes_from_prompt(client):
    p = client.get("/api/record/prompts", params={"speaker": "p01"}).json()["prompts"][0]
    for _ in range(2):
        client.post(f"/api/record/p01/{p['id']}", content=tone(2))
    rows = [json.loads(x) for x in record.MANIFEST.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["truth"] and rows[0]["condition"] == "phone"


@pytest.mark.parametrize(
    ("speaker", "body", "status"),
    [
        ("alloy", tone(2), 422),
        ("../x", tone(2), 404),
        ("p01", tone(0.3), 422),
        ("p01", tone(2, 0.001), 422),
        ("p01", b"junk", 422),
    ],
)
def test_rejects(client, speaker, body, status):
    pid = client.get("/api/record/prompts", params={"speaker": "p01"}).json()["prompts"][0]["id"]
    assert client.post(f"/api/record/{speaker}/{pid}", content=body).status_code == status


def test_extras_stay_out_of_the_locked_manifest(client):
    items = client.get("/api/record/extras", params={"speaker": "p01"}).json()["prompts"]
    assert len(items) == record.EXTRAS_PER_SPEAKER and {p["kind"] for p in items} == {"digits", "answer"}
    assert client.post(f"/api/record/p01/{items[0]['id']}", content=tone(2)).status_code == 200
    assert not record.MANIFEST.exists()
    row = json.loads((record.MANIFEST.with_name(record.EXTRAS_MANIFEST.name)).read_text())
    assert row["kind"] == items[0]["kind"] and row["truth"]
    again = client.get("/api/record/extras", params={"speaker": "p01"}).json()["prompts"]
    assert again[0]["done"]
