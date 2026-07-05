# genaudi SaaS — validation phase (design)

Goal: strangers upload a book, listen in browser, we measure demand.
No accounts, no billing. Compute pushed to the client so free tier costs ~nothing.

## Architecture

```
[Cloudflare Pages — static]                 [Fly.io — Docker]
  landing + app (Vite, vanilla TS)   ──►   FastAPI extract API
  kokoro-js synth in Web Worker             (extract.py reused, stateless)
  audio in OPFS, library in IndexedDB
```

## Components

### 1. Frontend (static, Vite + vanilla TS)
- **Landing**: value prop, email waitlist box, "Try it" → app. (Frontend host:
  Cloudflare Pages.)
- **App**: upload → `POST /api/extract` → chapter list → per-chapter Convert →
  kokoro-js (WebGPU, WASM fallback) in a Web Worker → audio blob in OPFS →
  `<audio>` player + MP3 download.
- **Library**: IndexedDB (book meta + chapter text + synth status). Survives
  reload. No server state.
- Model (~80MB) fetched once, cached by browser (Cache Storage via
  transformers.js).

### 2. Extract API (FastAPI, Docker, Fly.io)
- `POST /api/extract` — multipart PDF/EPUB, 25MB cap → `{title, chapters:[{title,text}]}`.
  Stores nothing; file processed in memory/tmp and discarded.
- `POST /api/waitlist` — `{email}` → SQLite on Fly volume. Validate format,
  dedupe.
- Per-IP rate limit: 10 extracts/day (in-memory counter, resets on deploy —
  fine at this scale).
- CORS locked to frontend origin.

### 3. Analytics
Cloudflare Web Analytics (free, same vendor as Pages) + custom events posted
to the API (`extract`, `synth_start`, `synth_done`, `waitlist_signup`) appended
to the same SQLite. This IS the validation instrument.

## Errors
- Scanned/image PDF → 422 "no extractable text — this looks like a scanned book".
- No WebGPU → WASM fallback + "slower on this device" notice.
- Extract API down → frontend shows retry; library still playable (local).

## Testing
- `tests/test_segment.py` unchanged (extraction logic untouched).
- Frontend: one headless smoke — chunk + synth one sentence, assert audio
  buffer non-empty.
- Manual E2E before launch: Gatsby EPUB through prod URL on laptop + phone.

## Known ceilings (deliberate)
- Browser synth slow on weak devices — that's a pricing finding, not a bug;
  server synth becomes the paid tier later.
- No cross-device sync — accounts later.
- Rate-limit state in memory — Redis when there's traffic worth counting.

## Skipped
Auth, billing, M4B stitch, server synth queue, voice picker (single voice),
GDPR beyond "we store only waitlist emails".

## Success criteria
Deployed URL; a stranger's browser can turn an EPUB into playable audio with
zero server compute per synth; waitlist + event counts visible.
