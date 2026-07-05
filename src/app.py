"""genaudi — local web UI: PDF/EPUB -> chapter MP3s. Run: uvicorn app:app"""
import json
import queue
import re
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import extract
import synth

ROOT = Path(__file__).resolve().parents[1]
BOOKS = ROOT / "books"
BOOKS.mkdir(exist_ok=True)

app = FastAPI(title="genaudi")
_meta_lock = threading.Lock()
_jobs = queue.Queue()


def _meta_path(book_id):
    return BOOKS / book_id / "meta.json"


def _load(book_id):
    p = _meta_path(book_id)
    if not p.exists():
        raise HTTPException(404, "book not found")
    return json.loads(p.read_text())


def _save(meta):
    with _meta_lock:
        _meta_path(meta["id"]).write_text(json.dumps(meta, indent=1))


def _set_status(book_id, idx, **fields):
    with _meta_lock:
        meta = json.loads(_meta_path(book_id).read_text())
        meta["chapters"][idx].update(fields)
        _meta_path(book_id).write_text(json.dumps(meta, indent=1))


def _worker():
    while True:
        book_id, idx = _jobs.get()
        d = BOOKS / book_id
        out = d / "audio" / f"{idx + 1:02d}.mp3"
        try:
            _set_status(book_id, idx, status="running", progress=0)
            text = (d / "chapters" / f"{idx + 1:02d}.txt").read_text()
            dur = synth.synth_chapter(
                text, str(out),
                progress=lambda done, total: _set_status(book_id, idx, progress=round(done / total, 2)),
            )
            _set_status(book_id, idx, status="done", duration=round(dur), progress=1)
        except Exception:
            traceback.print_exc()
            _set_status(book_id, idx, status="failed")


threading.Thread(target=_worker, daemon=True).start()


@app.post("/api/books")
async def upload(file: UploadFile):
    suffix = Path(file.filename or "book.pdf").suffix.lower()
    if suffix not in (".pdf", ".epub"):
        raise HTTPException(400, "only .pdf or .epub")
    book_id = re.sub(r"[^a-z0-9]+", "-", Path(file.filename).stem.lower()).strip("-") or "book"
    d = BOOKS / book_id
    if d.exists():
        raise HTTPException(409, f"'{book_id}' already uploaded")
    (d / "chapters").mkdir(parents=True)
    (d / "audio").mkdir()
    src = d / f"source{suffix}"
    src.write_bytes(await file.read())
    try:
        title, chapters = extract.extract_chapters(str(src))
    except Exception as e:
        import shutil
        shutil.rmtree(d)
        raise HTTPException(400, f"extraction failed: {e}")
    for i, (_, body) in enumerate(chapters):
        (d / "chapters" / f"{i + 1:02d}.txt").write_text(body)
    meta = {
        "id": book_id,
        "title": title or book_id,
        "chapters": [
            {"title": t, "chars": len(body), "status": "pending", "progress": 0, "duration": None}
            for t, body in chapters
        ],
    }
    _save(meta)
    return meta


@app.get("/api/books")
def list_books():
    return [json.loads(p.read_text()) for p in sorted(BOOKS.glob("*/meta.json"))]


@app.get("/api/books/{book_id}")
def get_book(book_id: str):
    return _load(book_id)


@app.post("/api/books/{book_id}/synth")
def synth_book(book_id: str, chapter: int | None = None):
    meta = _load(book_id)
    idxs = [chapter - 1] if chapter else range(len(meta["chapters"]))
    queued = 0
    for i in idxs:
        if not 0 <= i < len(meta["chapters"]):
            raise HTTPException(400, "bad chapter")
        if meta["chapters"][i]["status"] in ("pending", "failed"):
            _set_status(book_id, i, status="queued")
            _jobs.put((book_id, i))
            queued += 1
    return {"queued": queued}


app.mount("/audio", StaticFiles(directory=BOOKS), name="audio")  # /audio/<id>/audio/NN.mp3
app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="ui")
