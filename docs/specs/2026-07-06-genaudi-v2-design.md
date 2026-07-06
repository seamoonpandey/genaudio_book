# genaudi v2 — sellable SaaS design

Date: 2026-07-06. Approved in session. Supersedes the browser-TTS validation build.

## Decisions (locked)

- Full SaaS: accounts, free-tier quota, Stripe subscription. Sellable day one.
- TTS: Kokoro on own Fly workers (standard voice). Premium voices (ElevenLabs/OpenAI) later as a higher tier — engine abstraction in place, not wired.
- Reader: clean text e-reader view of extracted chapter text (what you see is what you hear).
- Pricing: Free = unlimited reading + 3 chapter conversions lifetime. Pro $9/mo = unlimited standard-voice conversions.
- UI: warm literary (Readwise/Audible/Matter pole). Serif display, warm paper tones, one oxblood accent.
- Features: upload PDF/EPUB → auto chapter segregation → read / convert per chapter / convert all / play / download / delete book.
- Server-side synthesis only. Browser TTS (kokoro-js worker) deleted.

## Architecture

```
CF Pages (React SPA)
   │ HTTPS/JSON, cookie auth
   ▼
Fly: genaudi-api (FastAPI, 1 machine, SQLite WAL on /data volume)
   │  auth, books, chapters, jobs, quota, Stripe webhook
   ├── Tigris S3 bucket: source files + mp3s (dev fallback: local disk)
   ▼
Fly: genaudi-worker (kokoro-onnx, autostop)
     claims jobs via API private-network endpoints → synth → upload mp3 → done
```

Worker never touches SQLite directly — talks to API over Fly private network
(`/internal/*`, bearer token) so SQLite stays single-writer.

## Data model (SQLite)

- `users` — id, email, google_id, plan (`free`/`pro`), chapters_converted, stripe_customer_id, created_at
- `sessions` — token_hash, user_id, expires_at
- `magic_links` — token_hash, email, expires_at
- `books` — id, user_id, title, author, source_key, status (`extracting`/`ready`/`failed`), error, created_at
- `chapters` — id, book_id, idx, title, text, chars, audio_key, duration, status (`none`/`queued`/`running`/`done`/`failed`), progress, error
- `jobs` — id, chapter_id, user_id, state (`queued`/`running`/`done`/`failed`), engine, attempts, claimed_by, claimed_at, error, created_at

## API surface

```
POST /auth/google            GET  /auth/me           POST /auth/logout
POST /auth/magic             POST /auth/magic/verify
POST /books                  GET  /books             GET /books/{id}   DELETE /books/{id}
GET  /books/{id}/chapters/{idx}                      (reader text)
POST /chapters/{id}/convert  POST /books/{id}/convert-all
GET  /books/{id}/progress    GET  /chapters/{id}/audio  (302 → signed URL)
POST /billing/checkout       POST /billing/portal    POST /webhooks/stripe
POST /internal/jobs/claim    POST /internal/jobs/{id}/progress
POST /internal/jobs/{id}/complete  POST /internal/jobs/{id}/fail
```

## Jobs pipeline

- Enqueue at `/convert`: quota `check_and_increment(user, n)` in one transaction; insert job rows.
- Worker claim: atomic UPDATE…WHERE id=(SELECT … LIMIT 1); round-robin across users (prefer users with no running job).
- Synth: existing `chunk_sentences` → kokoro-onnx → 64kbps MP3 (existing synth.py path) with progress callbacks → S3 upload.
- Recovery: `running` older than 15 min → back to `queued`; `attempts >= 3` → `failed` + error.
- Engine abstraction: `synthesize(text, voice, progress_cb) -> mp3_path`; `kokoro` now, `elevenlabs` later.
- Scaling: 1 worker machine, autostop; API starts it via Fly Machines API when queue non-empty.

## Auth + billing

- Google OAuth (server-side code flow) + magic-link email (Resend, 15-min token). No passwords.
- Session: 30-day httpOnly Secure SameSite=Lax cookie, token hashed in DB. Mutations require `X-Requested-With` header (CSRF belt+braces).
- Stripe: one price ($9/mo), Checkout Session, customer portal. Webhook handles `checkout.session.completed` (→pro), `customer.subscription.deleted` (→free), `invoice.payment_failed` (flag). Signature verified.
- Downgrade keeps existing audio, blocks new conversions past free quota.
- Dev fallbacks: `DEV_LOGIN=1` enables email-only login; missing Stripe keys disables billing endpoints (503); missing S3 creds falls back to local disk.

## Frontend (React + Vite + TS, CF Pages)

Screens: Landing (hero + drop zone + sample player + pricing), Library (book cards, progress rings, delete w/ confirm), Book view (chapter rows: read/convert/play/download/retry, convert-all), Reader (~68ch serif column, font stepper, light/dark, prev/next, position saved to localStorage), persistent bottom Player (speed 0.75–2×, ±30s, auto-advance), Account (plan, usage, Stripe portal).

Design system: paper `#FAF7F2` / dark `#1A1612`; accent oxblood `#9A3B2E`; Fraunces (display + reader body) + Inter (UI) self-hosted via fontsource; 1px warm borders, 8–10px radius; 150–200ms ease-out motion only; text ≥4.5:1 both themes; status never color-only.

Stack: React Router, TanStack Query (2s polling on active book only), CSS modules + custom-property tokens, no component library.

## Errors, testing, deploy

- Every failure = user-visible state with reason. API errors `{error:{code,message}}`. Sentry both sides (env-gated).
- pytest: extraction, quota, job claim/recovery, webhook fixtures, auth. vitest: player reducer. One Playwright smoke pre-deploy (signup → upload → convert → audio 200).
- Deploy: `genaudi-api` evolves in place; `genaudi-worker` new Fly app (models baked into image); SPA same CF Pages project. No data migration (v1 prod was stateless). Old browser-TTS code deleted.

## Cut from v2 (explicit)

Text-follows-audio highlighting, premium voices wiring, OCR for scanned PDFs, mobile apps, teams.
