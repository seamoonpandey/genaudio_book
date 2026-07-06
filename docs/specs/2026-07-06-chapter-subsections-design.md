# Chapter subsections — LLM-split sections (2026-07-06)

Pro users can split a long chapter into titled subsections using a small LLM
(Claude Haiku). Subsections surface in three places: reader navigation (jump
anchors), per-subsection audio conversion (shorter MP3s, finer progress), and
as the manual fix for page-based fallback chunks where heading detection failed.

Decisions made during brainstorm: Haiku API (not local model, not heuristics) ·
on-demand per chapter with result cached (not automatic at upload) · Pro-only
feature (free tier untouched, no quota interaction).

## Data model

`chapters` gains one column:

```sql
ALTER TABLE chapters ADD COLUMN parent_id INTEGER;  -- NULL = top-level
```

Applied as a guarded ALTER at startup (prod SQLite on the Fly volume already
exists; new installs get it in CREATE TABLE).

A subsection is a normal chapter row: same `book_id`, `parent_id` = parent
chapter id, `idx` = 0-based position within the parent, `title` from the LLM,
`text` = exact slice of the parent text, `chars` = len(text).

**Invariant: sections partition the parent exactly** — concatenating child
texts in idx order reproduces the parent text byte-for-byte. The reader derives
jump anchors from cumulative `chars`; no offset column.

Children must not leak into book-level views. Add `parent_id IS NULL` to:

- `GET /books` chapter-count join (`list_books`)
- `GET /books/{id}` chapter list (`get_book`)
- `GET /books/{id}/chapters/{idx}` idx lookup (`chapter_text`)
- `POST /books/{id}/convert-all` eligible-chapter query

`DELETE /books/{id}` already cascades by `book_id`, which children share — no
change.

## Split endpoint

`POST /chapters/{id}/split` (CSRF header required, like all mutations).

Order of checks:

1. Ownership via books join → 404 if not owned.
2. `user.plan != 'pro'` → **402 `pro_required`** ("splitting chapters is a Pro
   feature").
3. Chapter is itself a child (`parent_id` not NULL) → **400 `nested_split`**.
4. Children already exist → **200 with existing sections** (cached, idempotent,
   no re-split).
5. `chars < 4000` → **400 `too_short`**.
6. `ANTHROPIC_API_KEY` unset → **503** (same pattern as Stripe-less billing).

LLM call (sync, ~3–8 s, frontend shows spinner):

- Model: `claude-haiku-4-5` (verify exact id + pricing via claude-api reference
  at implementation time).
- Input: the chapter text as numbered paragraphs (`[0] …`, `[1] …`; paragraphs =
  blank-line splits).
- Asked output: JSON only —
  `{"sections":[{"title": "...", "start_paragraph": 0}, …]}`.
- **The LLM returns break points only, never text.** Sections are rebuilt by
  slicing the original paragraph list, so there is zero hallucination surface
  on book content.

Validation of the response: 2–20 sections; `start_paragraph` strictly
increasing; first is 0; all in range. On parse/validation failure retry once,
then **502 `split_failed`** with nothing inserted. On success insert all
children in one transaction and return the section list.

Cost ≈ $0.005–0.01 per split (30k-char chapter ≈ 8k input tokens at Haiku
pricing). Paid only by Pro users, only on demand, only once per chapter.

## Secrets

API loads `.env.secret` from the repo root at startup when the file exists —
a few-line stdlib parser (KEY=VALUE lines into `os.environ`, existing env
wins), no python-dotenv dependency. Production continues to use Fly secrets;
the file is a dev convenience and is gitignored.

## Audio + reader surface

No new audio code. `POST /chapters/{id}/convert`, progress polling,
`audio`/`audio-url`, and the player all key on chapter id — child ids work
as-is. (Free-tier quota counts a child conversion as 1 unit; only reachable if
a Pro user downgrades after splitting. Accepted.)

`GET /books/{b}/chapters/{idx}` response gains `"sections": [...]` — the
children as `_chapter_row`s in idx order — when the chapter is split; absent
otherwise.

Web (`web/`):

- Reader: "Split into sections" button (Pro-gated; 402 → upsell), section
  navigation with jump anchors, per-section convert/play.
- Book view: sections nested under their parent chapter row, expandable.

## Testing

Mock the Anthropic HTTP call (monkeypatch httpx in `api/test_v2.py` style).

- Happy path: sections inserted, partition invariant holds (concat == parent).
- Bad LLM output (non-JSON, out-of-range starts) → 502, no rows inserted.
- Free user → 402 `pro_required`.
- Second split call → 200 cached, no second LLM call.
- Child chapter converts through the existing queue.
- `GET /books` counts and `convert-all` exclude children.
- Splitting a child → 400 `nested_split`.
- Book delete removes children.

## Cut (deliberate)

Re-split/undo endpoint · automatic split at upload · auto-split of fallback
chunks during extract (user splits them with the same button) · nested splits ·
counting split cost against any quota.
