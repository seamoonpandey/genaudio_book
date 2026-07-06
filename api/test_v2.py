"""v2 API tests: auth, books, quota, worker queue, billing webhook."""
import hashlib
import hmac
import json
import time

import fitz
import pytest
from fastapi.testclient import TestClient

import db
from main import app

H = {"X-Requested-With": "genaudi"}
WH = {"Authorization": "Bearer test-worker-token"}

LOREM = (
    "Call me Ishmael. Some years ago, never mind how long precisely, having little "
    "or no money in my purse, and nothing particular to interest me on shore, I "
    "thought I would sail about a little and see the watery part of the world. It "
    "is a way I have of driving off the spleen and regulating the circulation. "
) * 6  # ~2000 chars: safely above extract.MIN_MAIN_CHARS so no chapter reads as front matter


def make_pdf(n_chapters=3) -> bytes:
    # filler lines vary per page so the header/footer stripper doesn't eat the headings
    doc = fitz.open()
    for i in range(n_chapters):
        page = doc.new_page()
        page.insert_textbox(
            fitz.Rect(72, 72, 520, 760),
            f"Opening line {i}.\nSecond line {i}.\nChapter {i + 1}\n{LOREM}",
            fontsize=11,
        )
    return doc.tobytes()


@pytest.fixture()
def client():
    for t in ("jobs", "chapters", "books", "sessions", "magic_links", "users"):
        db.ex(f"DELETE FROM {t}")
    return TestClient(app)


def login(client, email="a@example.com"):
    r = client.post("/auth/magic", json={"email": email}, headers=H)
    assert r.status_code == 200, r.text
    r = client.post("/auth/magic/verify", json={"token": r.json()["dev_token"]}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["user"]


def upload(client, n=3):
    r = client.post("/books", files={"file": (f"test-{n}.pdf", make_pdf(n), "application/pdf")},
                    headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_magic_login_and_me(client):
    user = login(client)
    assert user["plan"] == "pro"  # DEV_LOGIN=1 signups are pro
    r = client.get("/auth/me")
    assert r.json()["user"]["email"] == "a@example.com"


def test_csrf_blocks_headerless_mutation(client):
    r = client.post("/auth/magic", json={"email": "a@example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf"


def test_bad_magic_token(client):
    r = client.post("/auth/magic/verify", json={"token": "nope"}, headers=H)
    assert r.status_code == 400


def test_upload_reader_and_list(client):
    login(client)
    book = upload(client)
    assert len(book["chapters"]) >= 2
    assert book["chapters"][0]["status"] == "none"
    r = client.get(f"/books/{book['id']}/chapters/0")
    assert "Ishmael" in r.json()["text"]
    r = client.get("/books")
    assert r.json()[0]["chapters_total"] == len(book["chapters"])


def test_cross_user_isolation(client):
    login(client, "a@example.com")
    book = upload(client)
    client2 = TestClient(app)
    login(client2, "b@example.com")
    assert client2.get(f"/books/{book['id']}").status_code == 404
    assert client2.delete(f"/books/{book['id']}", headers=H).status_code == 404


def test_delete_cascades(client):
    login(client)
    book = upload(client)
    r = client.delete(f"/books/{book['id']}", headers=H)
    assert r.status_code == 200
    assert client.get(f"/books/{book['id']}").status_code == 404
    assert db.q1("SELECT COUNT(*) c FROM chapters WHERE book_id=?", (book["id"],))["c"] == 0


def test_free_quota_enforced(client):
    login(client, "quota@example.com")
    db.ex("UPDATE users SET plan='free' WHERE email=?", ("quota@example.com",))
    book = upload(client, n=5)
    chs = book["chapters"][:5]
    for ch in chs[:3]:
        r = client.post(f"/chapters/{ch['id']}/convert", headers=H)
        assert r.status_code == 200 and r.json()["queued"] == 1
    r = client.post(f"/chapters/{chs[3]['id']}/convert", headers=H)
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "quota_exceeded"


def test_convert_all_quota_atomic(client):
    login(client, "atomic@example.com")
    db.ex("UPDATE users SET plan='free' WHERE email=?", ("atomic@example.com",))
    book = upload(client, n=5)
    r = client.post(f"/books/{book['id']}/convert-all", headers=H)
    assert r.status_code == 402  # 5 > 3: nothing queued, nothing charged
    u = db.q1("SELECT chapters_converted FROM users WHERE email=?", ("atomic@example.com",))
    assert u["chapters_converted"] == 0


def test_worker_claim_complete_flow(client):
    login(client, "worker@example.com")
    book = upload(client)
    ch = book["chapters"][0]
    client.post(f"/chapters/{ch['id']}/convert", headers=H)
    r = client.post("/internal/jobs/claim", headers=WH)
    assert r.status_code == 200
    job = r.json()
    assert "Ishmael" in job["text"] and job["engine"] == "kokoro"
    r = client.post(f"/internal/jobs/{job['job_id']}/progress", json={"progress": 0.5}, headers=WH)
    assert r.status_code == 200
    r = client.post(
        f"/internal/jobs/{job['job_id']}/complete",
        files={"file": ("a.mp3", b"ID3fakemp3bytes", "audio/mpeg")},
        data={"duration": "123.4"}, headers=WH,
    )
    assert r.status_code == 200
    got = client.get(f"/books/{book['id']}").json()["chapters"][0]
    assert got["status"] == "done" and got["duration"] == 123.4
    r = client.get(f"/chapters/{ch['id']}/audio", follow_redirects=False)
    assert r.status_code == 302 and "/files/audio/" in r.headers["location"]


def test_worker_auth_required(client):
    assert client.post("/internal/jobs/claim").status_code == 401


def test_fail_retries_then_refunds(client):
    login(client, "fail@example.com")
    book = upload(client)
    ch = book["chapters"][0]
    client.post(f"/chapters/{ch['id']}/convert", headers=H)
    for attempt in range(3):
        job = client.post("/internal/jobs/claim", headers=WH).json()
        r = client.post(f"/internal/jobs/{job['job_id']}/fail", json={"error": "boom"}, headers=WH)
        assert r.status_code == 200
    got = client.get(f"/books/{book['id']}").json()["chapters"][0]
    assert got["status"] == "failed" and got["error"] == "boom"
    u = db.q1("SELECT chapters_converted FROM users WHERE email=?", ("fail@example.com",))
    assert u["chapters_converted"] == 0  # refunded


def test_claim_round_robin(client):
    login(client, "rr-a@example.com")
    book_a = upload(client)
    for ch in book_a["chapters"][:2]:
        client.post(f"/chapters/{ch['id']}/convert", headers=H)
    job_a = client.post("/internal/jobs/claim", headers=WH).json()  # A now running

    client2 = TestClient(app)
    login(client2, "rr-b@example.com")
    book_b = upload(client2)
    client2.post(f"/chapters/{book_b['chapters'][0]['id']}/convert", headers=H)

    nxt = client.post("/internal/jobs/claim", headers=WH).json()
    ch_b = db.q1("SELECT id FROM chapters WHERE book_id=? AND idx=0", (book_b["id"],))
    assert nxt["chapter_id"] == ch_b["id"], "user with no running job should be claimed first"
    assert nxt["job_id"] != job_a["job_id"]


def _stripe_event(event_type, customer_id):
    payload = json.dumps({
        "id": "evt_test", "object": "event", "type": event_type,
        "data": {"object": {"customer": customer_id}},
    })
    ts = int(time.time())
    sig = hmac.new(b"whsec_test", f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return payload, {"stripe-signature": f"t={ts},v1={sig}"}


def test_stripe_webhook_upgrades_plan(client):
    login(client, "pay@example.com")
    db.ex("UPDATE users SET stripe_customer_id='cus_1' WHERE email=?", ("pay@example.com",))
    payload, headers = _stripe_event("checkout.session.completed", "cus_1")
    r = client.post("/webhooks/stripe", content=payload, headers=headers)
    assert r.status_code == 200, r.text
    assert db.q1("SELECT plan FROM users WHERE email=?", ("pay@example.com",))["plan"] == "pro"
    payload, headers = _stripe_event("customer.subscription.deleted", "cus_1")
    client.post("/webhooks/stripe", content=payload, headers=headers)
    assert db.q1("SELECT plan FROM users WHERE email=?", ("pay@example.com",))["plan"] == "free"


def test_webhook_bad_signature_rejected(client):
    r = client.post("/webhooks/stripe", content="{}", headers={"stripe-signature": "t=1,v1=bad"})
    assert r.status_code == 400


def test_pro_user_unlimited(client):
    login(client, "pro@example.com")
    db.ex("UPDATE users SET plan='pro' WHERE email=?", ("pro@example.com",))
    book = upload(client, n=5)
    r = client.post(f"/books/{book['id']}/convert-all", headers=H)
    assert r.status_code == 200 and r.json()["queued"] == len(book["chapters"])
