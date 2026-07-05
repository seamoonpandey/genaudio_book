# genaudi build tasks

Autonomous build checklist. Spec: docs/specs/2026-07-05-genaudi-design.md

- [x] 1. venv + deps: fastapi uvicorn python-multipart pymupdf kokoro-onnx soundfile; download kokoro-v1.0.onnx + voices-v1.0.bin
- [x] 2. src/extract.py — PDF/EPUB → [(title, text)] via TOC → heading regex → page-chunk fallback; hyphenation + header/footer cleanup
- [x] 3. tests/test_segment.py — heuristic split + cleanup pass
- [x] 4. src/synth.py — chapter text → mp3 (sentence chunks → kokoro → ffmpeg); demo() smoke
- [x] 5. src/app.py — FastAPI: POST /api/books (upload), GET /api/books, GET /api/books/{id}, POST /api/books/{id}/synth[?chapter=N], audio static mount; background worker thread
- [x] 6. static/index.html — upload, chapter table w/ status, convert buttons, audio player; poll progress
- [x] 7. E2E: EPUB (TOC path) + 140-page PDF (heuristic path) → chapters sane → chapter synth → valid mp3
- [x] 8. Full book synth run (Gatsby I–IX, ~4h20m audio), git commit

All done — product works: upload book, see chapters, convert, listen at localhost:8765.

## SaaS validation phase (2026-07-05)

Plan: docs/plans/2026-07-05-genaudi-saas-validation.md — all tasks done.

- Frontend: https://genaudi.pages.dev (Cloudflare Pages, project `genaudi`)
- API: https://genaudi-api.fly.dev (Fly app `genaudi-api`, region sin, volume `data`)
- CORS locked to frontend origin; rate limit 10 extracts/day/IP
- Events + waitlist in SQLite: `flyctl ssh console -a genaudi-api -C "sqlite3 /data/genaudi.db 'select name,count(*) from events group by name'"`
- Remaining manual check: convert+play a chapter in a real browser at the prod URL (kokoro-js verified in node, not yet in browser)

Done when: upload Great Gatsby PDF in browser, see chapters, click convert, listen.
