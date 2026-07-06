"""genaudi API v2 — accounts, books, chapters, conversion queue, billing.
Run: uvicorn main:app (from api/, with src/ on path for extract)."""
import os
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    import extract  # container: extract.py sits next to main.py
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import extract

import billing
import db
import jobs
import storage
from auth import current_user
from auth import router as auth_router

MAX_BYTES = 25 * 1024 * 1024

app = FastAPI(title="genaudi-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
db.connect()


@app.exception_handler(HTTPException)
async def _err(request, exc: HTTPException):
    d = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    return JSONResponse({"error": d}, status_code=exc.status_code)


@app.middleware("http")
async def _csrf(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        p = request.url.path
        if not p.startswith("/webhooks") and not p.startswith("/internal"):
            if request.headers.get("x-requested-with") != "genaudi":
                return JSONResponse(
                    {"error": {"code": "csrf", "message": "missing X-Requested-With header"}},
                    status_code=403,
                )
    return await call_next(request)


app.include_router(auth_router)
app.include_router(billing.router)
app.include_router(jobs.internal)


def _book_row(b) -> dict:
    return {"id": b["id"], "title": b["title"], "author": b["author"],
            "status": b["status"], "error": b["error"], "created_at": b["created_at"]}


def _chapter_row(c) -> dict:
    return {"id": c["id"], "idx": c["idx"], "title": c["title"], "chars": c["chars"],
            "status": c["status"], "progress": c["progress"],
            "duration": c["duration"], "error": c["error"]}


def _owned_book(book_id: str, user):
    b = db.q1("SELECT * FROM books WHERE id=? AND user_id=?", (book_id, user["id"]))
    if not b:
        raise HTTPException(404, {"code": "not_found", "message": "book not found"})
    return b


@app.post("/books")
def upload(file: UploadFile, user=Depends(current_user)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".epub"):
        raise HTTPException(400, {"code": "bad_type", "message": "only .pdf or .epub"})
    data = file.file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, {"code": "too_big", "message": "max 25MB"})
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            title, chapters = extract.extract_chapters(tmp.name)
        except ValueError as e:
            raise HTTPException(422, {"code": "unextractable", "message": str(e)})
    book_id = secrets.token_hex(6)
    fallback = re.sub(r"[-_]+", " ", Path(file.filename or "Untitled").stem).strip()
    source_key = f"source/{user['id']}/{book_id}{suffix}"
    storage.put(source_key, data)
    now = int(time.time())
    with db.tx() as c:
        c.execute(
            "INSERT INTO books(id, user_id, title, source_key, status, created_at) "
            "VALUES(?,?,?,?, 'ready', ?)",
            (book_id, user["id"], title or fallback, source_key, now),
        )
        for i, (t, body) in enumerate(chapters):
            c.execute(
                "INSERT INTO chapters(book_id, idx, title, text, chars) VALUES(?,?,?,?,?)",
                (book_id, i, t, body, len(body)),
            )
    return get_book(book_id, user)


@app.get("/books")
def list_books(user=Depends(current_user)):
    rows = db.q(
        "SELECT b.*, COUNT(c.id) AS total, "
        "COALESCE(SUM(c.status='done'),0) AS done, COALESCE(SUM(c.duration),0) AS dur "
        "FROM books b LEFT JOIN chapters c ON c.book_id=b.id "
        "WHERE b.user_id=? GROUP BY b.id ORDER BY b.created_at DESC",
        (user["id"],),
    )
    return [{**_book_row(b), "chapters_total": b["total"], "chapters_done": b["done"],
             "duration": b["dur"]} for b in rows]


@app.get("/books/{book_id}")
def get_book(book_id: str, user=Depends(current_user)):
    b = _owned_book(book_id, user)
    chs = db.q("SELECT * FROM chapters WHERE book_id=? ORDER BY idx", (book_id,))
    return {**_book_row(b), "chapters": [_chapter_row(c) for c in chs]}


@app.delete("/books/{book_id}")
def delete_book(book_id: str, user=Depends(current_user)):
    _owned_book(book_id, user)
    with db.tx() as c:
        c.execute("DELETE FROM jobs WHERE chapter_id IN "
                  "(SELECT id FROM chapters WHERE book_id=?)", (book_id,))
        c.execute("DELETE FROM chapters WHERE book_id=?", (book_id,))
        c.execute("DELETE FROM books WHERE id=?", (book_id,))
    storage.delete_prefix(f"audio/{user['id']}/{book_id}")
    storage.delete_prefix(f"source/{user['id']}/{book_id}")
    return {"ok": True}


@app.get("/books/{book_id}/chapters/{idx}")
def chapter_text(book_id: str, idx: int, user=Depends(current_user)):
    _owned_book(book_id, user)
    ch = db.q1("SELECT * FROM chapters WHERE book_id=? AND idx=?", (book_id, idx))
    if not ch:
        raise HTTPException(404, {"code": "not_found", "message": "chapter not found"})
    total = db.q1("SELECT COUNT(*) AS n FROM chapters WHERE book_id=?", (book_id,))["n"]
    return {"idx": idx, "total": total, "title": ch["title"], "text": ch["text"],
            "status": ch["status"], "chapter_id": ch["id"]}


@app.post("/chapters/{chapter_id}/convert")
def convert_chapter(chapter_id: int, user=Depends(current_user)):
    ch = db.q1(
        "SELECT ch.id FROM chapters ch JOIN books b ON b.id=ch.book_id "
        "WHERE ch.id=? AND b.user_id=?", (chapter_id, user["id"]),
    )
    if not ch:
        raise HTTPException(404, {"code": "not_found", "message": "chapter not found"})
    return {"queued": jobs.enqueue(user, [chapter_id])}


@app.post("/books/{book_id}/convert-all")
def convert_all(book_id: str, user=Depends(current_user)):
    _owned_book(book_id, user)
    ids = [c["id"] for c in db.q("SELECT id FROM chapters WHERE book_id=?", (book_id,))]
    return {"queued": jobs.enqueue(user, ids)}


@app.get("/chapters/{chapter_id}/audio")
def audio(chapter_id: int, user=Depends(current_user)):
    ch = db.q1(
        "SELECT ch.audio_key FROM chapters ch JOIN books b ON b.id=ch.book_id "
        "WHERE ch.id=? AND b.user_id=?", (chapter_id, user["id"]),
    )
    if not ch or not ch["audio_key"]:
        raise HTTPException(404, {"code": "not_found", "message": "no audio for chapter"})
    return RedirectResponse(storage.url(ch["audio_key"]), status_code=302)


@app.get("/health")
def health():
    return {"ok": True}


# dev-only static audio when no S3 configured
if not (os.environ.get("BUCKET_NAME") or os.environ.get("S3_BUCKET")):
    _files = Path(os.environ.get("DATA_DIR", ".")) / "files"
    _files.mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=_files), name="files")
