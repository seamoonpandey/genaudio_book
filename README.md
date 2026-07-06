# genaudi

Turn any PDF or EPUB you own into an audiobook. Upload → chapters detected → read in a clean e-reader view, convert chapters to audio server-side, listen in a persistent player or download MP3s.

**v2 is a full SaaS**: accounts (magic link + Google), free tier (unlimited reading, 3 chapter conversions), Pro $9/mo via Stripe (unlimited conversions), server-side Kokoro TTS on a worker fleet. Spec: `docs/specs/2026-07-06-genaudi-v2-design.md`.

## Architecture

```
CF Pages (React SPA — warm literary UI)
   │ HTTPS/JSON, httpOnly session cookie
   ▼
Fly: genaudi-api ── FastAPI, SQLite (WAL) on /data volume
   │   auth · books · chapters · job queue · quota · Stripe webhooks
   ├── Tigris S3: uploaded sources + MP3s (local disk in dev)
   ▼ private network, bearer token
Fly: genaudi-worker ── claims jobs → kokoro-onnx → MP3 → posts back
```

Key properties:
- **Worker never touches the DB** — it claims/completes jobs via `/internal/*` endpoints over Fly's private network, so SQLite keeps a single writer.
- **Quota is transactional** — free tier = 3 chapter conversions lifetime, checked+incremented at enqueue in one transaction; refunded if a job permanently fails. Enforced server-side.
- **Crash-safe queue** — jobs `running` >15 min are requeued; 3 failed attempts → `failed` with a user-visible reason and a Retry button.
- **Engine abstraction** — `worker/engines.py` exposes `synthesize(text, voice, progress_cb)`; Kokoro now, premium voices (ElevenLabs/OpenAI) drop in as a higher tier later.

## Repo layout

```
api/        FastAPI: main (books/chapters/convert), auth, jobs, billing, db, storage
worker/     TTS worker: claim loop + engines, own Dockerfile/fly.toml
web/        React + Vite SPA (CF Pages) — library, book view, reader, player, account
src/        extract.py (chapterization, shared), synth.py (kokoro+ffmpeg, used by worker)
tests/      extraction tests · api/test_v2.py — API/quota/queue/webhook tests
models/     kokoro-v1.0.onnx + voices-v1.0.bin (local dev; baked into worker image)
docs/       specs + plans
```

The uvicorn API (`api/`) is backend-only — JSON over HTTPS, no HTML. The only UI is the React SPA in `web/`. (The old v1 single-machine app that served its own HTML from uvicorn was removed.)

## Run locally

Prereqs: Python 3.12+, Node 20+, `ffmpeg`. Models in `models/` (worker only):

```bash
mkdir -p models
curl -L -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o models/voices-v1.0.bin  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
python -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt kokoro-onnx soundfile numpy
```

Three terminals:

```bash
# 1 — API (dev mode: magic-link login without email, files on local disk)
cd api && DEV_LOGIN=1 WORKER_TOKEN=dev ../.venv/bin/uvicorn main:app --port 8000

# 2 — worker
cd worker && API_URL=http://127.0.0.1:8000 WORKER_TOKEN=dev ../.venv/bin/python worker.py

# 3 — frontend
cd web && npm install && npm run dev   # http://localhost:5173
```

Sign in with any email (dev mode skips the actual email), drop a PDF/EPUB, convert, listen. Billing endpoints return 503 until Stripe env is set; the UI says so.

## Tests

```bash
.venv/bin/pytest api tests      # 18 tests: auth, CSRF, quota, queue, webhooks, extraction
cd web && npm test              # player state machine
cd web && npm run build         # typecheck + bundle
```

Verified E2E locally: dev login → upload Gatsby EPUB (12 chapters) → convert → real worker synthesizes → valid MP3 (ffprobe) → quota counter increments.

## API surface

```
POST /auth/magic  /auth/magic/verify  /auth/google   GET /auth/me   POST /auth/logout
POST /books                GET /books            GET|DELETE /books/{id}
GET  /books/{id}/chapters/{idx}                  (reader text)
POST /chapters/{id}/convert   POST /books/{id}/convert-all      (402 = quota)
GET  /chapters/{id}/audio     GET /chapters/{id}/audio-url
POST /billing/checkout  /billing/portal  /webhooks/stripe
POST /internal/jobs/claim|{id}/progress|{id}/complete|{id}/fail  (worker, bearer token)
```

Errors are always `{"error":{"code","message"}}`. Mutations require `X-Requested-With: genaudi` (CSRF) except Stripe webhook and internal routes.

## Deploy

Secrets you need once (API app):

```bash
flyctl secrets set -a genaudi-api \
  WORKER_TOKEN=$(openssl rand -hex 24) \
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... \
  RESEND_API_KEY=... MAIL_FROM="genaudi <login@yourdomain>" \
  STRIPE_SECRET_KEY=sk_live_... STRIPE_PRICE_ID=price_... STRIPE_WEBHOOK_SECRET=whsec_... \
  BUCKET_NAME=... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_ENDPOINT_URL_S3=https://fly.storage.tigris.dev
# Tigris bucket: flyctl storage create -a genaudi-api  (fills the AWS_* values)
# worker gets the same WORKER_TOKEN:
flyctl secrets set -a genaudi-worker WORKER_TOKEN=<same value>
```

Deploys (from repo root):

```bash
flyctl deploy -c api/fly.toml                 # API (existing app genaudi-api)
flyctl apps create genaudi-worker && flyctl deploy -c worker/fly.toml   # worker (once), then deploy
cd web && VITE_API_BASE=https://genaudi-api.fly.dev VITE_GOOGLE_CLIENT_ID=... npm run build \
  && npx wrangler pages deploy dist --project-name genaudi --branch main
```

Stripe wiring: create one $9/mo price, point a webhook at `https://genaudi-api.fly.dev/webhooks/stripe` with events `checkout.session.completed`, `customer.subscription.deleted`, `invoice.payment_failed`. Google OAuth: authorized redirect URI `https://genaudi.pages.dev/login`.

Note: API runs `min_machines_running = 1` — the worker claims jobs over the private network, and internal traffic can't auto-start a stopped machine.

## Design system (web)

Warm literary: paper `#FAF7F2` / dark `#181310`, oxblood accent `#8C3226`, Fraunces (display + reader) with Inter (UI), generated cloth-bound book covers (title-hashed cloth palette) as the visual signature, drop caps in the reader, 150–200ms motion only, both themes ≥4.5:1 contrast, statuses never color-only.

## Cut from v2 (deliberate)

Text-follows-audio highlighting, premium voice tier wiring, OCR for scanned PDFs, mobile apps, teams. Each waits on demand.
