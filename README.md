# genaudi

Turn any PDF or EPUB into an audiobook. Upload a book, get chapters, convert each chapter to MP3 with the [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) TTS model, and listen.

Two deployables live in this repo:

| App | What | Where it runs | TTS runs on |
|-----|------|---------------|-------------|
| **Local app** (`src/` + `static/`) | Full pipeline: upload → extract → synthesize → serve MP3s | Your machine (`uvicorn`, port 8765) | Server (kokoro-onnx + ffmpeg) |
| **SaaS validation** (`web/` + `api/`) | Landing page + in-browser synthesis; server only extracts chapters | [genaudi.pages.dev](https://genaudi.pages.dev) + [genaudi-api.fly.dev](https://genaudi-api.fly.dev) | Browser (kokoro-js in a Web Worker, WebGPU or WASM) |

Both share the same extraction logic (`src/extract.py`) and the same sentence-chunking approach.

## How it works

```
                    ┌─────────────────────────────────────────────┐
 PDF / EPUB ──────▶ │ extract.py (PyMuPDF)                        │
                    │  1. TOC split (if the file has a real TOC)  │
                    │  2. heading-regex split ("Chapter 7", "VII")│
                    │  3. fallback: 15-page chunks                │
                    │  + strip running headers/footers,           │
                    │    de-hyphenate, unwrap hard line breaks    │
                    └──────────────┬──────────────────────────────┘
                                   │  [(chapter title, clean text)]
                                   ▼
                    ┌─────────────────────────────────────────────┐
                    │ synthesis                                   │
                    │  split into ≤400-char sentence chunks       │
                    │  → Kokoro TTS per chunk (voice af_heart,    │
                    │    24 kHz) + 0.3 s pause between chunks     │
                    │  → encode to 64 kbps MP3                    │
                    └──────────────┬──────────────────────────────┘
                                   │
              local app: ffmpeg → books/<id>/audio/NN.mp3
              web app:   lamejs → OPFS blob, played/downloaded in-browser
```

### Extraction (`src/extract.py`)

`extract_chapters(path)` returns `(book_title, [(chapter_title, text)])`. It tries three strategies in order and takes the first that yields ≥2 chapters:

1. **TOC** — PyMuPDF's `get_toc()`, top-level entries (level ≤2 if too few at level 1).
2. **Heading regex** — lines matching `Chapter/Part/Book/Section N`, bare numerals, or Roman numerals alone on a line. Front matter before the first heading becomes its own chapter.
3. **Page chunks** — dumb 15-page slices, so no book ever comes back as one giant blob.

Before splitting, lines that repeat on >30% of pages (running heads, page numbers) are stripped. After splitting, hyphenation across line breaks is repaired and hard-wrapped lines are joined into paragraphs. Chapters under 200 chars (covers, blanks) are dropped. A scanned/image-only PDF raises `ValueError`.

### Synthesis

Text is split at sentence boundaries and packed into ≤400-char chunks (Kokoro degrades on long inputs). Each chunk is synthesized separately with a 0.3 s silence between chunks, then everything is concatenated and MP3-encoded at 64 kbps.

- **Server-side** (`src/synth.py`): `kokoro-onnx` against `models/kokoro-v1.0.onnx` + `models/voices-v1.0.bin`, WAV via soundfile, MP3 via `ffmpeg`. Rough throughput: a full novel (Gatsby, ~4h20m of audio) takes a while — chapters run one at a time on a single background worker thread.
- **In-browser** (`web/src/synth-worker.ts`): `kokoro-js` loads the q8 ONNX model from HuggingFace (`onnx-community/Kokoro-82M-v1.0-ONNX`) inside a Web Worker, using WebGPU when available and WASM otherwise. MP3 encoding via `@breezystack/lamejs`. First conversion downloads the model (~80 MB); it stays cached after that.

## Repo layout

```
src/            local app: extract.py, synth.py, app.py (FastAPI)
static/         local app UI (single index.html, polls /api/books)
tests/          pytest for extraction/segmentation
models/         kokoro-v1.0.onnx + voices-v1.0.bin (server-side TTS)
books/          local app data: books/<id>/{source,meta.json,chapters/,audio/}

web/            SaaS frontend (Vite + TypeScript, no framework)
  src/app.ts        UI, synth queue, waitlist, event tracking
  src/synth-worker.ts  kokoro-js + MP3 encode in a Web Worker
  src/chunk.ts      sentence chunker (TS twin of synth.py's)
  src/db.ts         IndexedDB (book metadata) + OPFS (MP3 blobs)
api/            SaaS backend (FastAPI): stateless extract + waitlist/events
  main.py, Dockerfile, fly.toml, test_api.py

docs/specs/     design docs
docs/plans/     validation-phase plan
TASKS.md        build checklist / status
```

## Setup

### Prerequisites

- Python 3.12+ (local app also needs `ffmpeg` on PATH)
- Node 20+ (web frontend only)

### Local app (full server-side pipeline)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # fastapi uvicorn python-multipart pymupdf kokoro-onnx soundfile
```

Download the TTS model into `models/` (not committed — ~310 MB + ~27 MB):

```bash
mkdir -p models
curl -L -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o models/voices-v1.0.bin  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Run:

```bash
cd src && uvicorn app:app --port 8765
```

Open http://localhost:8765 — upload a PDF/EPUB, chapters appear, click convert, listen. Books and MP3s persist under `books/`. If the process dies mid-synthesis, stale `running`/`queued` chapters reset to `pending` on next start, so retry works.

### SaaS API (extract-only backend)

```bash
pip install -r api/requirements.txt   # no TTS deps — extraction only
cd api && uvicorn main:app --port 8000
```

Env vars: `FRONTEND_ORIGIN` (CORS allowlist, defaults `*`), `DATA_DIR` (SQLite location, defaults cwd).

### SaaS frontend

```bash
cd web
npm install
npm run dev        # Vite dev server; expects API at http://localhost:8000
```

Point at a different API with `VITE_API_BASE=https://genaudi-api.fly.dev npm run dev`.

Books live in IndexedDB, MP3s in OPFS (Origin Private File System) — all client-side, nothing uploaded except the source file for extraction.

## Tests

```bash
# extraction + segmentation
source .venv/bin/activate && pytest tests/ api/

# frontend (sentence chunker)
cd web && npm test

# TTS smoke test (one sentence → playable MP3)
cd src && python synth.py

# web build (typecheck + bundle)
cd web && npm run build
```

## API reference

### SaaS API (`api/main.py` — genaudi-api.fly.dev)

| Endpoint | Method | Body | Returns |
|----------|--------|------|---------|
| `/api/extract` | POST | multipart `file` (.pdf/.epub, ≤25 MB) | `{title, chapters: [{title, text}]}` |
| `/api/waitlist` | POST | `{email}` | `{ok: true}` |
| `/api/event` | POST | `{name}` — one of `extract`, `synth_start`, `synth_done`, `waitlist_signup` | `{ok: true}` |
| `/api/health` | GET | — | `{ok: true}` |

Rate limit: 10 extracts/day/IP (in-memory counter — resets on machine restart, which is fine for a validation phase). Errors: `400` bad type/email, `413` too big, `422` unextractable (scanned PDF), `429` rate limited.

### Local app (`src/app.py` — localhost:8765)

| Endpoint | Method | What |
|----------|--------|------|
| `/api/books` | POST | multipart `file` upload → extract → returns book meta |
| `/api/books` | GET | list all books with per-chapter status |
| `/api/books/{id}` | GET | one book's meta (UI polls this for progress) |
| `/api/books/{id}/synth?chapter=N` | POST | queue chapter N (1-based) or all pending/failed chapters |
| `/audio/{id}/audio/NN.mp3` | GET | static MP3 |
| `/` | GET | UI |

Chapter status lifecycle: `pending → queued → running (progress 0–1) → done` (or `failed`, retryable).

## Deployment

### API → Fly.io (app `genaudi-api`, region sin)

```bash
flyctl deploy -c api/fly.toml       # from repo root — Dockerfile copies src/extract.py + api/main.py
```

Machine: shared-cpu-1x, 512 MB, scales to zero. 1 GB volume `data` mounted at `/data` holds `genaudi.db` (waitlist + events).

Check demand signal:

```bash
flyctl ssh console -a genaudi-api -C "sqlite3 /data/genaudi.db 'select name,count(*) from events group by name'"
```

### Frontend → Cloudflare Pages (project `genaudi`)

```bash
cd web
VITE_API_BASE=https://genaudi-api.fly.dev npm run build
npx wrangler pages deploy dist --project-name genaudi --branch main
```

## Design docs

- `docs/specs/2026-07-05-genaudi-design.md` — v1 (local pipeline) design
- `docs/specs/2026-07-05-genaudi-saas-design.md` — SaaS validation design
- `docs/plans/2026-07-05-genaudi-saas-validation.md` — validation-phase plan
- `TASKS.md` — build checklist and current status

## Known limits

- English only, single voice (`af_heart`).
- Scanned/image PDFs are rejected — no OCR.
- Browser synthesis is single-chapter-at-a-time; a long chapter on a WASM-only device is slow.
- Rate limiting and events are best-effort (in-memory / SQLite) — deliberate, this is a validation phase.
