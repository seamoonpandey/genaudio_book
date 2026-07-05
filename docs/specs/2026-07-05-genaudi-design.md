# genaudi — PDF/EPUB → chapter-segmented audiobook (design)

Personal tool, local web UI, Kokoro TTS on CPU, MP3 per chapter.

## Pipeline

upload → extract → segment → synthesize → play/download

1. **Extract/segment** (`PyMuPDF`): open PDF/EPUB → embedded TOC (`doc.get_toc()`)
   for chapter boundaries → fallback: regex heading heuristic ("Chapter N", roman
   numerals, numbered headings) → last resort: split every ~15 pages. Clean
   hyphenation and repeated headers/footers.
2. **Storage**: `books/<slug>/` — `chapters/NN.txt`, `audio/NN.mp3`, `meta.json`
   (title, chapter list, per-chapter status). Filesystem is the database.
3. **Synthesis** (`kokoro-onnx` + ffmpeg): sentence-chunk chapter text (~400 chars),
   synth chunks, concat waveform, encode MP3. One chapter at a time in background
   thread; `meta.json` status: `pending/running/done/failed`. Resumable — done
   chapters skipped.
4. **Web UI**: single `static/index.html`, vanilla JS. Upload → chapter list with
   status → convert all / per-chapter → `<audio>` player + download. Polls
   `/api/books/<id>`.
5. **Errors**: bad file → 400 with message; chapter failure → `failed` + retry,
   others continue.
6. **Tests**: `tests/test_segment.py` (TOC + heuristic). `synth.py` smoke demo.

## Skipped (add when needed)

Auth, DB, job queue, M4B stitch, voice selection UI, GPU.
