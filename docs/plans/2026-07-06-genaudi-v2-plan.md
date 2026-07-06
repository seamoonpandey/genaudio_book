# genaudi v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Spec: docs/specs/2026-07-06-genaudi-v2-design.md

**Goal:** Sellable SaaS: accounts + Stripe, server-side Kokoro TTS via job queue, warm-literary React UI with library/reader/player.

**Architecture:** React SPA (CF Pages) → FastAPI on Fly (SQLite WAL, single writer) → Fly worker claims jobs over private-network internal API, synthesizes with kokoro-onnx, posts MP3 back; storage on Tigris S3 with local-disk dev fallback.

**Tech Stack:** FastAPI, SQLite, stripe, httpx, boto3 · kokoro-onnx, ffmpeg · React 18, Vite, TS, React Router, TanStack Query, CSS modules, Fraunces/Inter (fontsource).

## Global Constraints

- Files under 500 lines (CLAUDE.md)
- Quota enforced server-side in one transaction; free = 3 chapter conversions lifetime; refund on permanent failure
- Worker never opens SQLite — internal API only, bearer `WORKER_TOKEN`
- Dev fallbacks: `DEV_LOGIN=1` (magic token returned in response, no email), no S3 env → local disk under `DATA_DIR/files`, no Stripe env → billing endpoints 503
- Mutations require `X-Requested-With: genaudi` header except `/webhooks/stripe` and `/internal/*`
- All API errors `{"error":{"code","message"}}`; every failure user-visible with reason
- Contrast ≥4.5:1 both themes; status chips never color-only

---

### Task 1: DB + storage layer
**Files:** Create `api/db.py`, `api/storage.py`. Test: `api/test_v2.py`
**Produces:** `db.connect()` (module-global conn, WAL), `db.init()` DDL per spec tables, `db.q(sql, args)` / `db.q1` / `db.ex` helpers with lock; `storage.put(key, data)`, `storage.url(key)` (presigned or `/files/{key}`), `storage.delete_prefix(prefix)`, `storage.get(key)`.
Steps: failing tests for quota-free schema round-trip + local storage put/get/url → implement → pass → commit.

### Task 2: Auth (sessions, magic link, Google, CSRF)
**Files:** Create `api/auth.py`. Modify `api/main.py`. Test: `api/test_v2.py`
**Produces:** `router` (`/auth/*`), `current_user` dependency (403 if none), `create_session(resp, user_id)`, `get_or_create_user(email, google_id=None)`. Magic: `POST /auth/magic {email}` → store sha256(token), 15-min expiry, Resend send (skip + return `dev_token` when `DEV_LOGIN=1`); `POST /auth/magic/verify {token}` → session cookie. Google: exchange code via httpx, `id_token` payload → email/sub. CSRF middleware.
Tests: magic-link dev flow end-to-end, CSRF reject, bad token 400.

### Task 3: Books + chapters + reader endpoints
**Files:** Rewrite `api/main.py` (routers: auth, books, billing, internal). Test: `api/test_v2.py`
**Produces:** `POST /books` (multipart, 25MB, pdf/epub, extract via src/extract.py, rows in books+chapters, source → storage), `GET /books`, `GET /books/{id}`, `DELETE /books/{id}` (cascade + storage.delete_prefix), `GET /books/{id}/chapters/{idx}` → `{idx,total,title,text}`, `GET /books/{id}/progress` → chapters status/progress/duration, `GET /chapters/{id}/audio` → 302 storage.url. All owner-scoped (404 cross-user).
Tests: upload gatsby.epub fixture → chapters >2; cross-user 404; delete cascades.

### Task 4: Quota + job queue + internal endpoints
**Files:** Create `api/jobs.py`. Test: `api/test_v2.py`
**Produces:** `enqueue(user, chapter_ids)` — one transaction: free-plan check `chapters_converted + n <= 3` else 402 `quota_exceeded`, increment counter, insert jobs, chapters→`queued`; `POST /chapters/{id}/convert`, `POST /books/{id}/convert-all` (skips done/queued); internal router: `POST /internal/jobs/claim` (requeue stale >15 min first; round-robin: queued jobs from users w/o running job first; returns `{job_id, chapter_id, text, engine, voice}` or 204), `POST /internal/jobs/{id}/progress {progress}`, `POST /internal/jobs/{id}/complete` (multipart mp3 + duration → storage `audio/{user}/{book}/{idx}.mp3`, chapter done), `POST /internal/jobs/{id}/fail {error}` (attempts<3 → requeue else failed + quota refund for free plan). Bearer `WORKER_TOKEN`.
Tests: quota 402 on 4th free conversion; claim round-robin; stale requeue; fail→refund.

### Task 5: Stripe billing
**Files:** Create `api/billing.py`. Test: `api/test_v2.py`
**Produces:** `POST /billing/checkout` → Checkout Session URL (customer lazy), `POST /billing/portal`, `POST /webhooks/stripe` verifying signature, handling `checkout.session.completed`→pro, `customer.subscription.deleted`→free, `invoice.payment_failed`→`payment_failed=1`. 503 when `STRIPE_SECRET_KEY` unset.
Tests: webhook with test signature updates plan (stripe lib `Webhook.construct_event` with test secret).

### Task 6: Worker
**Files:** Create `worker/worker.py`, `worker/engines.py`, `worker/Dockerfile`, `worker/fly.toml`, `worker/requirements.txt`.
**Produces:** `engines.get("kokoro").synthesize(text, voice, progress_cb) -> (mp3_bytes, duration)` reusing `src/synth.py` chunking+kokoro+ffmpeg; loop: claim → synth (progress POST each chunk batch) → complete; on exception → fail. Env: `API_URL`, `WORKER_TOKEN`, model paths. Poll 3s when 204.
Test: engine interface smoke behind `GENAUDI_SMOKE=1` (needs models); loop logic unit-tested with mocked httpx.

### Task 7: Frontend scaffold + design system + auth
**Files:** Rewrite `web/` (delete app.ts, synth-worker.ts, db.ts, chunk*.ts): `package.json`, `vite.config.ts`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/api.ts`, `src/types.ts`, `src/tokens.css`, `src/global.css`, `src/pages/Login.tsx`.
**Produces:** tokens (paper/dark, oxblood accent, Fraunces+Inter), router with auth gate (`/auth/me`), Login page (Google redirect when `VITE_GOOGLE_CLIENT_ID` set + magic-link email form), api client (credentials, `X-Requested-With`, `{error}` normalize).

### Task 8: Library + upload + delete
**Files:** `src/pages/Library.tsx`, `src/components/UploadZone.tsx`, `src/components/BookCard.tsx`, `src/components/Modal.tsx` (+ css modules).
**Produces:** grid of cards (generated cover: warm gradient + serif initial, progress ring), drag-anywhere upload, optimistic "Extracting…" card, delete confirm modal listing consequences.

### Task 9: Book view + convert + polling
**Files:** `src/pages/Book.tsx` (+ css).
**Produces:** chapter rows with status chips + actions per state (Read/Convert/Play/Download/Retry), Convert-all with quota message on 402, TanStack Query polling 2s while any queued/running.

### Task 10: Reader
**Files:** `src/pages/Reader.tsx` (+ css).
**Produces:** ~68ch serif column, font stepper, theme toggle, prev/next, localStorage position, mini-player link when audio exists.

### Task 11: Persistent player
**Files:** `src/player.tsx`, `src/player.test.ts`.
**Produces:** context + reducer (queue = book chapters, auto-advance), bottom bar (play/pause, ±30s, speed 0.75–2×, progress). Vitest on reducer (advance, speed, seek).

### Task 12: Landing + account
**Files:** `src/pages/Landing.tsx`, `src/pages/Account.tsx` (+ css), `web/public/sample.mp3` (75s cut of gatsby ch1).
**Produces:** hero + drop zone → login redirect, sample player, pricing (Free vs Pro $9), Account: plan, x/3 usage, checkout/portal buttons, logout.

### Task 13: Ship
Steps: `pytest api tests` green; `npm test` + `npm run build` green; update `api/Dockerfile` (copies api/*.py + src/extract.py), `api/requirements.txt` (+stripe, boto3, httpx); README v2 rewrite; commits per task; final commit.
Deploy (needs user secrets — documented, not executed): Fly secrets for API (SESSION/WORKER tokens, Google, Stripe, Resend, Tigris), `fly launch` worker, CF Pages deploy.
