"""genaudi extract API — stateless extraction + waitlist/event log."""
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

try:
    import extract  # container: extract.py sits next to main.py
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import extract

MAX_BYTES = 25 * 1024 * 1024
DAILY_LIMIT = 10
EVENTS = {"extract", "synth_start", "synth_done", "waitlist_signup"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title="genaudi-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "*")],
    allow_methods=["*"],
    allow_headers=["*"],
)

_db_path = Path(os.environ.get("DATA_DIR", ".")) / "genaudi.db"
_conn = sqlite3.connect(_db_path, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS waitlist(email TEXT PRIMARY KEY, ts INT)")
_conn.execute("CREATE TABLE IF NOT EXISTS events(name TEXT, ts INT)")
_conn.commit()
_rate = {}  # ponytail: in-memory per-IP counter, Redis when traffic exists


def _check_rate(ip):
    day = time.strftime("%Y%m%d")
    d, n = _rate.get(ip, (day, 0))
    if d != day:
        n = 0
    if n >= DAILY_LIMIT:
        raise HTTPException(429, "daily limit reached — come back tomorrow")
    _rate[ip] = (day, n + 1)


def _log(name):
    _conn.execute("INSERT INTO events VALUES(?,?)", (name, int(time.time())))
    _conn.commit()


@app.post("/api/extract")
async def extract_book(file: UploadFile, request: Request):
    _check_rate(request.client.host)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".epub"):
        raise HTTPException(400, "only .pdf or .epub")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "max 25MB")
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            title, chapters = extract.extract_chapters(tmp.name)
        except ValueError as e:
            raise HTTPException(422, str(e))
    _log("extract")
    return {"title": title, "chapters": [{"title": t, "text": b} for t, b in chapters]}


@app.post("/api/waitlist")
def waitlist(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "invalid email")
    _conn.execute("INSERT OR IGNORE INTO waitlist VALUES(?,?)", (email, int(time.time())))
    _conn.commit()
    _log("waitlist_signup")
    return {"ok": True}


@app.post("/api/event")
def event(payload: dict):
    name = payload.get("name")
    if name not in EVENTS:
        raise HTTPException(400, "unknown event")
    _log(name)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}
