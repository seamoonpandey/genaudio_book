# genaudi build tasks

Autonomous build checklist. Spec: docs/specs/2026-07-05-genaudi-design.md

- [ ] 1. venv + deps: fastapi uvicorn python-multipart pymupdf kokoro-onnx soundfile; download kokoro-v1.0.onnx + voices-v1.0.bin
- [ ] 2. src/extract.py — PDF/EPUB → [(title, text)] via TOC → heading regex → page-chunk fallback; hyphenation + header/footer cleanup
- [ ] 3. tests/test_segment.py — heuristic split + cleanup pass
- [ ] 4. src/synth.py — chapter text → mp3 (sentence chunks → kokoro → ffmpeg); demo() smoke
- [ ] 5. src/app.py — FastAPI: POST /api/books (upload), GET /api/books, GET /api/books/{id}, POST /api/books/{id}/synth[?chapter=N], audio static mount; background worker thread
- [ ] 6. static/index.html — upload, chapter table w/ status, convert buttons, audio player; poll progress
- [ ] 7. E2E: real public-domain PDF → chapters look sane → synth one chapter → valid mp3
- [ ] 8. Full book synth run, git commit

Done when: upload Great Gatsby PDF in browser, see chapters, click convert, listen.
