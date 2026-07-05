# genaudi SaaS Validation Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deployable validation product — strangers upload PDF/EPUB, chapters extracted server-side, audio synthesized in their browser (kokoro-js), demand measured via events + waitlist.

**Architecture:** Static Vite frontend (Cloudflare Pages) does synthesis in a Web Worker via kokoro-js (WebGPU→WASM fallback), stores MP3s in OPFS and library in IndexedDB. Small stateless FastAPI service (Fly.io, Docker) reuses `src/extract.py` for extraction and records waitlist/events in SQLite.

**Tech Stack:** Python 3.12/FastAPI/PyMuPDF (API), Vite + vanilla TypeScript, kokoro-js, @breezystack/lamejs (MP3 encode), vitest.

## Global Constraints

- Spec: `docs/specs/2026-07-05-genaudi-saas-design.md`
- `src/extract.py` is reused UNCHANGED — do not edit it
- Upload cap 25MB; rate limit 10 extracts/day/IP (in-memory); event names exactly: `extract`, `synth_start`, `synth_done`, `waitlist_signup`
- API stores nothing from uploads; only waitlist emails + event rows in SQLite at `$DATA_DIR/genaudi.db`
- Voice: `af_heart`, model `onnx-community/Kokoro-82M-v1.0-ONNX`, dtype `q8`
- Frontend reads API base from `VITE_API_BASE` (default `http://localhost:8000`)
- Keep files under 500 lines
- Python venv: `.venv/bin/python` at repo root; run API tests with `.venv/bin/python -m pytest`

---

### Task 1: Extract API service

**Files:**
- Create: `api/main.py`
- Create: `api/requirements.txt`
- Test: `api/test_api.py`

**Interfaces:**
- Consumes: `extract.extract_chapters(path) -> (title, [(chapter_title, text)])` from `src/extract.py`
- Produces: HTTP API — `POST /api/extract` → `{title, chapters:[{title,text}]}`; `POST /api/waitlist` `{email}` → `{ok:true}`; `POST /api/event` `{name}` → `{ok:true}`

- [ ] **Step 1: Write requirements**

`api/requirements.txt`:
```
fastapi
uvicorn
python-multipart
pymupdf
```

Install test deps: `.venv/bin/pip install httpx pytest`

- [ ] **Step 2: Write the failing test**

`api/test_api.py`:
```python
import io
import sys
from pathlib import Path

import fitz
import pytest
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
    _rate["testclient"] = (__import__("time").strftime("%Y%m%d"), 10)
    r = client.post("/api/extract", files={"file": ("book.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")})
    assert r.status_code == 429
    _rate.clear()


def test_waitlist_and_event():
    assert client.post("/api/waitlist", json={"email": "a@b.co"}).status_code == 200
    assert client.post("/api/waitlist", json={"email": "nope"}).status_code == 400
    assert client.post("/api/event", json={"name": "synth_done"}).status_code == 200
    assert client.post("/api/event", json={"name": "hax"}).status_code == 400
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest api/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 4: Write implementation**

`api/main.py`:
```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest api/test_api.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add api/
git commit -m "feat(api): stateless extract API with waitlist + events"
```

---

### Task 2: Dockerfile + Fly config

**Files:**
- Create: `api/Dockerfile`
- Create: `api/fly.toml`
- Create: `api/.dockerignore`

**Interfaces:**
- Consumes: `api/main.py`, `src/extract.py`
- Produces: container exposing port 8080; Fly app named `genaudi-api` with volume `data` mounted at `/data`

- [ ] **Step 1: Write Dockerfile**

`api/Dockerfile` (build context = repo root):
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/extract.py api/main.py ./
ENV DATA_DIR=/data
RUN mkdir -p /data
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`api/.dockerignore`:
```
test_api.py
```

- [ ] **Step 2: Write fly.toml**

`api/fly.toml`:
```toml
app = "genaudi-api"
primary_region = "sin"

[build]
  dockerfile = "Dockerfile"

[env]
  DATA_DIR = "/data"

[[mounts]]
  source = "data"
  destination = "/data"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

- [ ] **Step 3: Verify container builds and serves (if docker available; else skip to commit, Fly builds remotely)**

Run from repo root:
```bash
docker build -f api/Dockerfile -t genaudi-api . && docker run -d --rm -p 8080:8080 --name genaudi-api genaudi-api && sleep 3 && curl -s http://localhost:8080/api/health && docker stop genaudi-api
```
Expected: `{"ok":true}`

- [ ] **Step 4: Commit**

```bash
git add api/Dockerfile api/fly.toml api/.dockerignore
git commit -m "feat(api): Dockerfile + fly.toml"
```

---

### Task 3: Frontend scaffold + shared chunker with test

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/chunk.ts`
- Test: `web/src/chunk.test.ts`

**Interfaces:**
- Produces: `chunkSentences(text: string, maxChars = 400): string[]` — used by Task 4 worker
- Produces: `web/index.html` with element ids used by Task 5: `#waitlist-form`, `#waitlist-email`, `#file`, `#books`, `#player`, `#msg`

- [ ] **Step 1: Scaffold**

```bash
mkdir -p web/src
```

`web/package.json`:
```json
{
  "name": "genaudi-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "@breezystack/lamejs": "^1.2.7",
    "kokoro-js": "^1.2.1"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

`web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "lib": ["ES2022", "DOM", "WebWorker"],
    "types": ["vite/client"]
  },
  "include": ["src"]
}
```

`web/vite.config.ts`:
```ts
import { defineConfig } from "vite";
export default defineConfig({
  worker: { format: "es" },
  build: { target: "es2022" },
});
```

Run: `cd web && npm install`

- [ ] **Step 2: Write the failing chunker test**

`web/src/chunk.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { chunkSentences } from "./chunk";

describe("chunkSentences", () => {
  it("packs sentences under limit", () => {
    const chunks = chunkSentences("One. Two. Three.", 12);
    expect(chunks).toEqual(["One. Two.", "Three."]);
  });
  it("hard-splits pathological runs", () => {
    const chunks = chunkSentences("x".repeat(950), 400);
    expect(chunks.length).toBe(3);
    expect(Math.max(...chunks.map((c) => c.length))).toBeLessThanOrEqual(400);
  });
  it("drops empty input", () => {
    expect(chunkSentences("   ", 400)).toEqual([]);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run`
Expected: FAIL — cannot resolve `./chunk`

- [ ] **Step 4: Implement chunker (port of synth.py chunk_sentences)**

`web/src/chunk.ts`:
```ts
export function chunkSentences(text: string, maxChars = 400): string[] {
  const sentences = text.split(/(?<=[.!?”"])\s+/);
  const chunks: string[] = [];
  let cur = "";
  for (let s of sentences) {
    s = s.trim();
    if (!s) continue;
    while (s.length > maxChars) {
      chunks.push(s.slice(0, maxChars));
      s = s.slice(maxChars);
    }
    if (cur.length + s.length + 1 > maxChars && cur) {
      chunks.push(cur);
      cur = s;
    } else {
      cur = cur ? `${cur} ${s}` : s;
    }
  }
  if (cur) chunks.push(cur);
  return chunks;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run`
Expected: 3 passed

- [ ] **Step 6: Write index.html (landing + app, one page)**

`web/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>genaudi — turn any ebook into an audiobook, free, in your browser</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { max-width: 760px; margin: 0 auto; padding: 0 1rem 4rem; }
    header { text-align: center; padding: 3rem 0 2rem; }
    h1 { font-size: 2rem; margin: 0 0 .5rem; }
    .sub { opacity: .8; margin-bottom: 1.5rem; }
    #waitlist-form { display: flex; gap: .5rem; justify-content: center; }
    #waitlist-email { padding: .5rem; min-width: 16rem; }
    #drop { border: 2px dashed #8888; border-radius: 8px; padding: 2rem; text-align: center; margin-top: 2rem; }
    table { width: 100%; border-collapse: collapse; }
    td, th { padding: .4rem .5rem; text-align: left; border-bottom: 1px solid #8884; }
    td:first-child { max-width: 22rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    button { cursor: pointer; }
    .status-done { color: #2a2 } .status-failed { color: #d33 }
    .status-running, .status-loading { color: #e90 }
    #msg { color: #d33; min-height: 1.2em; }
    #device-note { font-size: .85rem; opacity: .7; }
    audio { width: 100%; margin-top: 1rem; }
    h2 { font-size: 1.1rem; margin: 1.5rem 0 .5rem; }
  </style>
</head>
<body>
  <header>
    <h1>genaudi</h1>
    <p class="sub">Turn any PDF or EPUB into an audiobook — free, private, right in your browser. Your book never leaves your device except to split chapters; the voice is generated locally.</p>
    <form id="waitlist-form">
      <input type="email" id="waitlist-email" placeholder="email — get launch updates" required>
      <button>Join waitlist</button>
    </form>
  </header>

  <div id="drop">
    <input type="file" id="file" accept=".pdf,.epub">
    <p>PDF or EPUB → chapters → listen</p>
    <p id="device-note"></p>
  </div>
  <p id="msg"></p>
  <div id="books"></div>
  <audio id="player" controls hidden></audio>

  <script type="module" src="/src/app.ts"></script>
</body>
</html>
```

- [ ] **Step 7: Commit**

```bash
git add web/
git commit -m "feat(web): scaffold, landing page, sentence chunker + tests"
```

---

### Task 4: Synth worker (kokoro-js → MP3 blob)

**Files:**
- Create: `web/src/synth-worker.ts`

**Interfaces:**
- Consumes: `chunkSentences` from `web/src/chunk.ts`
- Produces: Worker protocol —
  in: `{ text: string }`;
  out: `{ type: "loading" } | { type: "progress", done: number, total: number } | { type: "done", mp3: Blob, duration: number } | { type: "error", message: string }`

- [ ] **Step 1: Write worker**

`web/src/synth-worker.ts`:
```ts
import { KokoroTTS } from "kokoro-js";
import { Mp3Encoder } from "@breezystack/lamejs";
import { chunkSentences } from "./chunk";

const MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";
const VOICE = "af_heart";
const RATE = 24000;
const PAUSE = new Int16Array(RATE * 0.3); // beat between chunks

let tts: KokoroTTS | null = null;

function toInt16(f32: Float32Array): Int16Array {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

self.onmessage = async (e: MessageEvent<{ text: string }>) => {
  try {
    if (!tts) {
      postMessage({ type: "loading" });
      const device = "gpu" in navigator ? "webgpu" : "wasm";
      tts = await KokoroTTS.from_pretrained(MODEL, { dtype: "q8", device });
    }
    const chunks = chunkSentences(e.data.text);
    const enc = new Mp3Encoder(1, RATE, 64);
    const parts: Uint8Array[] = [];
    let samples = 0;
    for (let i = 0; i < chunks.length; i++) {
      const audio = await tts.generate(chunks[i], { voice: VOICE });
      const pcm = toInt16(audio.audio as Float32Array);
      parts.push(enc.encodeBuffer(pcm), enc.encodeBuffer(PAUSE));
      samples += pcm.length + PAUSE.length;
      postMessage({ type: "progress", done: i + 1, total: chunks.length });
    }
    parts.push(enc.flush());
    postMessage({
      type: "done",
      mp3: new Blob(parts as BlobPart[], { type: "audio/mpeg" }),
      duration: samples / RATE,
    });
  } catch (err) {
    postMessage({ type: "error", message: String(err) });
  }
};
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors (adjust kokoro-js typings with `as` casts only if the published types disagree)

- [ ] **Step 3: Commit**

```bash
git add web/src/synth-worker.ts
git commit -m "feat(web): kokoro-js synth worker with MP3 encode"
```

---

### Task 5: App logic — IndexedDB library, OPFS audio, UI wiring

**Files:**
- Create: `web/src/db.ts`
- Create: `web/src/app.ts`

**Interfaces:**
- Consumes: extract API (`VITE_API_BASE`), worker protocol from Task 4, element ids from Task 3
- Produces: `db.ts` — `getBooks(): Promise<Book[]>`, `putBook(b: Book): Promise<void>`; types:
  `type Chapter = { title: string; text: string; status: "pending"|"loading"|"running"|"done"|"failed"; progress: number; duration: number | null }`,
  `type Book = { id: string; title: string; chapters: Chapter[] }`

- [ ] **Step 1: Write db.ts**

`web/src/db.ts`:
```ts
export type Chapter = {
  title: string;
  text: string;
  status: "pending" | "loading" | "running" | "done" | "failed";
  progress: number;
  duration: number | null;
};
export type Book = { id: string; title: string; chapters: Chapter[] };

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("genaudi", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("books", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const req = fn(db.transaction("books", mode).objectStore("books"));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export const getBooks = () => tx<Book[]>("readonly", (s) => s.getAll());
export const putBook = (b: Book) => tx("readwrite", (s) => s.put(b)).then(() => {});

export async function saveAudio(name: string, blob: Blob): Promise<void> {
  const dir = await navigator.storage.getDirectory();
  const fh = await dir.getFileHandle(name, { create: true });
  const w = await fh.createWritable();
  await w.write(blob);
  await w.close();
}

export async function audioURL(name: string): Promise<string> {
  const dir = await navigator.storage.getDirectory();
  const fh = await dir.getFileHandle(name);
  return URL.createObjectURL(await fh.getFile());
}
```

- [ ] **Step 2: Write app.ts**

`web/src/app.ts`:
```ts
import { audioURL, Book, getBooks, putBook, saveAudio } from "./db";

const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const $ = <T extends HTMLElement>(s: string) => document.querySelector(s) as T;
const esc = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

let books: Book[] = [];
let worker: Worker | null = null;
let busy = false;
const queue: { bookId: string; idx: number }[] = [];

function track(name: string) {
  fetch(`${API}/api/event`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  }).catch(() => {});
}

$("#device-note")!.textContent =
  "gpu" in navigator ? "" : "No WebGPU on this device — synthesis will be slower (WASM).";

($("#waitlist-form") as HTMLFormElement).onsubmit = async (e) => {
  e.preventDefault();
  const email = ($("#waitlist-email") as HTMLInputElement).value;
  const r = await fetch(`${API}/api/waitlist`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email }),
  });
  $("#msg")!.textContent = r.ok ? "You're on the list." : (await r.json()).detail;
};

($("#file") as HTMLInputElement).onchange = async (e) => {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  $("#msg")!.textContent = "extracting…";
  const fd = new FormData();
  fd.append("file", f);
  try {
    const r = await fetch(`${API}/api/extract`, { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail);
    const data = await r.json();
    const book: Book = {
      id: `${Date.now()}`,
      title: data.title || f.name,
      chapters: data.chapters.map((c: { title: string; text: string }) => ({
        ...c, status: "pending", progress: 0, duration: null,
      })),
    };
    await putBook(book);
    books.push(book);
    $("#msg")!.textContent = "";
    render();
  } catch (err) {
    $("#msg")!.textContent = String(err instanceof Error ? err.message : err);
  }
};

function synth(bookId: string, idx: number) {
  queue.push({ bookId, idx });
  const b = books.find((x) => x.id === bookId)!;
  b.chapters[idx].status = "loading";
  void putBook(b);
  render();
  pump();
}

function pump() {
  if (busy) return;
  const job = queue.shift();
  if (!job) return;
  busy = true;
  const book = books.find((b) => b.id === job.bookId)!;
  const ch = book.chapters[job.idx];
  ch.status = "running";
  track("synth_start");
  if (!worker) worker = new Worker(new URL("./synth-worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = async (e) => {
    const m = e.data;
    if (m.type === "progress") ch.progress = m.done / m.total;
    if (m.type === "done") {
      await saveAudio(`${book.id}-${job.idx}.mp3`, m.mp3);
      ch.status = "done";
      ch.duration = Math.round(m.duration);
      track("synth_done");
    }
    if (m.type === "error") {
      ch.status = "failed";
      $("#msg")!.textContent = m.message;
    }
    if (m.type === "done" || m.type === "error") {
      await putBook(book);
      busy = false;
      pump();
    }
    render();
  };
  worker.postMessage({ text: ch.text });
}

async function play(bookId: string, idx: number) {
  const p = $("#player") as HTMLAudioElement;
  p.hidden = false;
  p.src = await audioURL(`${bookId}-${idx}.mp3`);
  void p.play();
}

async function download(bookId: string, idx: number, title: string) {
  const a = document.createElement("a");
  a.href = await audioURL(`${bookId}-${idx}.mp3`);
  a.download = `${String(idx + 1).padStart(2, "0")}-${title.replace(/[^a-z0-9]+/gi, "-")}.mp3`;
  a.click();
}

function render() {
  $("#books")!.innerHTML = books
    .map(
      (b) => `
    <h2>${esc(b.title)} <button data-all="${b.id}">Convert all</button></h2>
    <table>${b.chapters
      .map((c, i) => {
        const st = c.status === "running" ? `running ${Math.round(c.progress * 100)}%`
          : c.status === "loading" ? "fetching voice model…" : c.status;
        const act =
          c.status === "done"
            ? `<button data-play="${b.id}:${i}">▶</button> <button data-dl="${b.id}:${i}">↓</button>`
            : c.status === "pending" || c.status === "failed"
              ? `<button data-synth="${b.id}:${i}">${c.status === "failed" ? "retry" : "convert"}</button>`
              : "";
        const mins = c.duration ? ` · ${Math.round(c.duration / 60)}m` : "";
        return `<tr><td title="${esc(c.title)}">${i + 1}. ${esc(c.title)}</td>
          <td>${Math.round(c.text.length / 1000)}k${mins}</td>
          <td class="status-${c.status}">${st}</td><td>${act}</td></tr>`;
      })
      .join("")}</table>`,
    )
    .join("");
  document.querySelectorAll<HTMLButtonElement>("[data-synth]").forEach((el) => {
    el.onclick = () => { const [id, i] = el.dataset.synth!.split(":"); synth(id, +i); };
  });
  document.querySelectorAll<HTMLButtonElement>("[data-play]").forEach((el) => {
    el.onclick = () => { const [id, i] = el.dataset.play!.split(":"); void play(id, +i); };
  });
  document.querySelectorAll<HTMLButtonElement>("[data-dl]").forEach((el) => {
    el.onclick = () => {
      const [id, i] = el.dataset.dl!.split(":");
      const b = books.find((x) => x.id === id)!;
      void download(id, +i, b.chapters[+i].title);
    };
  });
  document.querySelectorAll<HTMLButtonElement>("[data-all]").forEach((el) => {
    el.onclick = () => {
      const b = books.find((x) => x.id === el.dataset.all)!;
      b.chapters.forEach((c, i) => {
        if (c.status === "pending" || c.status === "failed") synth(b.id, i);
      });
    };
  });
}

getBooks().then((bs) => {
  // stale in-flight statuses from a closed tab -> pending
  books = bs.map((b) => ({
    ...b,
    chapters: b.chapters.map((c) =>
      c.status === "running" || c.status === "loading" ? { ...c, status: "pending" as const } : c,
    ),
  }));
  render();
});
```

- [ ] **Step 3: Typecheck + unit tests + build**

Run: `cd web && npx tsc --noEmit && npx vitest run && npm run build`
Expected: clean typecheck, 3 tests pass, `dist/` produced

- [ ] **Step 4: Local smoke against local API**

```bash
cd api && ../.venv/bin/uvicorn main:app --port 8000 &   # or reuse running instance
cd web && npm run dev &
curl -s http://localhost:8000/api/health
```
Expected: `{"ok":true}`; dev server on 5173. Verify in browser: upload `scratchpad/gatsby.epub`, chapters render, Convert on smallest chapter produces playable audio (model download ~90MB on first run).

- [ ] **Step 5: Commit**

```bash
git add web/src/db.ts web/src/app.ts
git commit -m "feat(web): library, OPFS audio, synth queue UI"
```

---

### Task 6: Deploy (HUMAN GATE — needs Fly + Cloudflare credentials)

**Files:**
- Modify: `TASKS.md` (record prod URLs)

**Interfaces:**
- Consumes: everything above
- Produces: public frontend URL + API URL

- [ ] **Step 1: Deploy API to Fly**

```bash
flyctl auth login              # human
cd api
flyctl launch --no-deploy --copy-config --name genaudi-api
flyctl volumes create data --size 1
flyctl secrets set FRONTEND_ORIGIN=https://<pages-domain>
flyctl deploy --dockerfile Dockerfile --build-context ..   # context = repo root
curl -s https://genaudi-api.fly.dev/api/health
```
Expected: `{"ok":true}`

- [ ] **Step 2: Deploy frontend to Cloudflare Pages**

```bash
cd web
VITE_API_BASE=https://genaudi-api.fly.dev npm run build
npx wrangler pages deploy dist --project-name genaudi   # human: wrangler login
```
Then set real `FRONTEND_ORIGIN` on Fly to the Pages URL and redeploy API. Enable CF Web Analytics on the Pages project (dashboard toggle).

- [ ] **Step 3: Prod E2E**

Upload Gatsby EPUB at the Pages URL; convert chapter; play. Check events:
```bash
flyctl ssh console -C "sqlite3 /data/genaudi.db 'select name,count(*) from events group by name'"
```

- [ ] **Step 4: Commit**

```bash
git add TASKS.md
git commit -m "chore: record prod URLs, validation phase live"
```
