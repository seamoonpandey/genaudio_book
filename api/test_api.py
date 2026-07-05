import io
import sys
import time
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from main import app, _rate

client = TestClient(app)


def _pdf_bytes():
    doc = fitz.open()
    for n in (1, 2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Chapter {n}")
        for line in range(30):
            page.insert_text((72, 100 + line * 12), f"Sentence {line} of chapter {n} goes here.")
    return doc.tobytes()


def test_extract_returns_chapters():
    r = client.post("/api/extract", files={"file": ("book.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["chapters"]) == 2
    assert "Sentence 3" in data["chapters"][0]["text"]


def test_extract_rejects_other_types():
    r = client.post("/api/extract", files={"file": ("book.txt", io.BytesIO(b"hi"), "text/plain")})
    assert r.status_code == 400


def test_rate_limit():
    _rate.clear()
    _rate["testclient"] = (time.strftime("%Y%m%d"), 10)
    r = client.post("/api/extract", files={"file": ("book.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")})
    assert r.status_code == 429
    _rate.clear()


def test_waitlist_and_event():
    assert client.post("/api/waitlist", json={"email": "a@b.co"}).status_code == 200
    assert client.post("/api/waitlist", json={"email": "nope"}).status_code == 400
    assert client.post("/api/event", json={"name": "synth_done"}).status_code == 200
    assert client.post("/api/event", json={"name": "hax"}).status_code == 400
