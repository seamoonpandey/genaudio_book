"""Job queue: quota-checked enqueue + internal worker endpoints (bearer-auth)."""
import os
import time

from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile

import db
import storage

FREE_LIMIT = 3
STALE_SECONDS = 900
MAX_ATTEMPTS = 3

internal = APIRouter(prefix="/internal")


def _now() -> int:
    return int(time.time())


def enqueue(user, chapter_ids: list[int]) -> int:
    """Queue eligible chapters. One transaction: quota check + increment + inserts.
    Raises 402 when a free user would exceed the lifetime limit."""
    with db.tx() as c:
        rows = c.execute(
            f"SELECT id FROM chapters WHERE id IN ({','.join('?' * len(chapter_ids))}) "
            "AND status IN ('none','failed')",
            chapter_ids,
        ).fetchall()
        eligible = [r["id"] for r in rows]
        n = len(eligible)
        if n == 0:
            return 0
        if user["plan"] == "free":
            used = c.execute(
                "SELECT chapters_converted FROM users WHERE id=?", (user["id"],)
            ).fetchone()[0]
            left = FREE_LIMIT - used
            if n > left:
                raise HTTPException(402, {
                    "code": "quota_exceeded",
                    "message": f"free plan: {left} of {FREE_LIMIT} conversions left — upgrade for unlimited",
                })
            c.execute(
                "UPDATE users SET chapters_converted=chapters_converted+? WHERE id=?",
                (n, user["id"]),
            )
        for cid in eligible:
            c.execute(
                "INSERT INTO jobs(chapter_id, user_id, created_at) VALUES(?,?,?)",
                (cid, user["id"], _now()),
            )
            c.execute(
                "UPDATE chapters SET status='queued', progress=0, error=NULL WHERE id=?",
                (cid,),
            )
    return n


def _refund(c, user_id: int):
    c.execute(
        "UPDATE users SET chapters_converted=MAX(chapters_converted-1,0) "
        "WHERE id=? AND plan='free'",
        (user_id,),
    )


def _require_worker(request: Request):
    token = os.environ.get("WORKER_TOKEN", "")
    got = request.headers.get("authorization", "")
    if not token or got != f"Bearer {token}":
        raise HTTPException(401, {"code": "unauthorized", "message": "bad worker token"})


def _job(c, job_id: int, state="running"):
    row = c.execute("SELECT * FROM jobs WHERE id=? AND state=?", (job_id, state)).fetchone()
    if not row:
        raise HTTPException(404, {"code": "not_found", "message": "no such running job"})
    return row


@internal.post("/jobs/claim")
def claim(request: Request):
    _require_worker(request)
    now = _now()
    with db.tx() as c:
        # requeue jobs whose worker died mid-run
        stale = c.execute(
            "SELECT id, chapter_id FROM jobs WHERE state='running' AND claimed_at<?",
            (now - STALE_SECONDS,),
        ).fetchall()
        for s in stale:
            c.execute("UPDATE jobs SET state='queued', claimed_by=NULL WHERE id=?", (s["id"],))
            c.execute("UPDATE chapters SET status='queued' WHERE id=?", (s["chapter_id"],))
        # round-robin: users with nothing running go first
        row = c.execute(
            "SELECT j.id, j.chapter_id, j.engine, ch.text FROM jobs j "
            "JOIN chapters ch ON ch.id=j.chapter_id WHERE j.state='queued' "
            "ORDER BY (j.user_id IN (SELECT user_id FROM jobs WHERE state='running')), "
            "j.created_at LIMIT 1"
        ).fetchone()
        if not row:
            return Response(status_code=204)
        c.execute(
            "UPDATE jobs SET state='running', claimed_by=?, claimed_at=?, attempts=attempts+1 "
            "WHERE id=?",
            (request.headers.get("x-worker-id", "worker"), now, row["id"]),
        )
        c.execute("UPDATE chapters SET status='running', progress=0 WHERE id=?", (row["chapter_id"],))
    return {"job_id": row["id"], "chapter_id": row["chapter_id"],
            "engine": row["engine"], "voice": "af_heart", "text": row["text"]}


@internal.post("/jobs/{job_id}/progress")
def progress(job_id: int, payload: dict, request: Request):
    _require_worker(request)
    with db.tx() as c:
        job = _job(c, job_id)
        c.execute(
            "UPDATE chapters SET progress=? WHERE id=?",
            (min(max(float(payload.get("progress", 0)), 0), 1), job["chapter_id"]),
        )
    return {"ok": True}


@internal.post("/jobs/{job_id}/complete")
async def complete(job_id: int, request: Request, file: UploadFile, duration: float = Form()):
    _require_worker(request)
    data = await file.read()
    with db.tx() as c:
        job = _job(c, job_id)
        ch = c.execute(
            "SELECT ch.idx, ch.book_id, b.user_id FROM chapters ch "
            "JOIN books b ON b.id=ch.book_id WHERE ch.id=?",
            (job["chapter_id"],),
        ).fetchone()
        key = f"audio/{ch['user_id']}/{ch['book_id']}/{ch['idx']:02d}.mp3"
        storage.put(key, data)
        c.execute(
            "UPDATE chapters SET status='done', progress=1, audio_key=?, duration=?, error=NULL "
            "WHERE id=?",
            (key, duration, job["chapter_id"]),
        )
        c.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
    return {"ok": True}


@internal.post("/jobs/{job_id}/fail")
def fail(job_id: int, payload: dict, request: Request):
    _require_worker(request)
    err = str(payload.get("error", "unknown"))[:500]
    with db.tx() as c:
        job = _job(c, job_id)
        if job["attempts"] >= MAX_ATTEMPTS:
            c.execute("UPDATE jobs SET state='failed', error=? WHERE id=?", (err, job_id))
            c.execute(
                "UPDATE chapters SET status='failed', error=? WHERE id=?",
                (err, job["chapter_id"]),
            )
            _refund(c, job["user_id"])
        else:
            c.execute("UPDATE jobs SET state='queued', claimed_by=NULL WHERE id=?", (job_id,))
            c.execute("UPDATE chapters SET status='queued' WHERE id=?", (job["chapter_id"],))
    return {"ok": True}
