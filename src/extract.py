"""PDF/EPUB -> list of (title, text) chapters. PyMuPDF only."""
import re
from collections import Counter

import fitz

# "Chapter 7", "CHAPTER VII", "7.", "VII", "Part 2" ... alone on a line
HEADING_RE = re.compile(
    r"^\s*(chapter|part|book|section)\s+([0-9]+|[ivxlc]+)\b.{0,60}$"
    r"|^\s*([0-9]{1,3}|[IVXLC]{1,7})\.?\s*$",
    re.IGNORECASE,
)
PAGES_PER_FALLBACK_CHUNK = 15
MIN_CHAPTER_CHARS = 200  # drop cover/blank fragments
MIN_MAIN_CHARS = 1500    # leading chapters shorter than this = front matter (title page, epigraph)

# front/back matter nobody wants read aloud
JUNK_TITLE_RE = re.compile(
    r"^(table of )?contents$|acknowledg|copyright|dedication|^index$|bibliograph"
    r"|glossary|about the author|also by |title page|^cover$|colophon"
    r"|list of (figures|tables|illustrations)|^notes$|praise for ",
    re.IGNORECASE,
)


def strip_front_matter(chapters):
    """Drop junk-titled chapters anywhere, then trim leading short chapters so the
    book starts at real content. Never trims the whole book away."""
    kept = [(t, b) for t, b in chapters if not JUNK_TITLE_RE.search(t.strip())]
    start = 0
    while start < len(kept) - 1 and len(kept[start][1]) < MIN_MAIN_CHARS:
        start += 1
    trimmed = kept[start:]
    return trimmed if trimmed else chapters


def _page_texts(doc):
    return [page.get_text("text") for page in doc]


def _strip_headers_footers(pages):
    """Drop lines repeating on >30% of pages (running heads, page numbers)."""
    counts = Counter()
    for t in pages:
        lines = t.splitlines()
        for ln in set(lines[:2] + lines[-2:]):
            key = re.sub(r"\d+", "#", ln.strip().lower())
            if key:
                counts[key] += 1
    threshold = max(3, len(pages) * 0.3)
    junk = {k for k, c in counts.items() if c >= threshold}

    def clean(t):
        out = []
        for i, ln in enumerate(t.splitlines()):
            key = re.sub(r"\d+", "#", ln.strip().lower())
            edge = i < 2 or i >= len(t.splitlines()) - 2
            if edge and key in junk:
                continue
            out.append(ln)
        return "\n".join(out)

    return [clean(t) for t in pages]


def clean_text(text):
    """Fix hyphenation, collapse hard wraps into paragraphs."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # de-hyphenate
    text = re.sub(r"\n{2,}", "\0", text)                   # keep para breaks
    text = re.sub(r"\s*\n\s*", " ", text)                  # unwrap lines
    text = text.replace("\0", "\n\n")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _split_by_toc(doc, pages):
    toc = [(lvl, title, pg) for lvl, title, pg in doc.get_toc() if pg > 0]
    if len(toc) < 2:
        return None
    # top-level entries only; if too few, take level<=2
    top = [e for e in toc if e[0] == 1]
    if len(top) < 2:
        top = [e for e in toc if e[0] <= 2]
    chapters = []
    for i, (_, title, pg) in enumerate(top):
        end = top[i + 1][2] - 1 if i + 1 < len(top) else len(pages)
        body = "\n".join(pages[pg - 1:max(pg - 1 + 1, end)])
        chapters.append((title.strip(), clean_text(body)))
    return chapters


def _split_by_headings(pages):
    full = "\n".join(pages)
    lines = full.splitlines()
    marks = [i for i, ln in enumerate(lines) if HEADING_RE.match(ln)]
    if len(marks) < 2:
        return None
    chapters = []
    for j, i in enumerate(marks):
        end = marks[j + 1] if j + 1 < len(marks) else len(lines)
        title = lines[i].strip()
        body = "\n".join(lines[i + 1:end])
        chapters.append((title, clean_text(body)))
    if marks[0] > 0:  # front matter before first heading
        front = clean_text("\n".join(lines[:marks[0]]))
        if len(front) >= MIN_CHAPTER_CHARS:
            chapters.insert(0, ("Front matter", front))
    return chapters


def _split_by_pages(pages):
    # ponytail: dumb page chunks, last resort so no book is one giant blob
    chapters = []
    for i in range(0, len(pages), PAGES_PER_FALLBACK_CHUNK):
        body = clean_text("\n".join(pages[i:i + PAGES_PER_FALLBACK_CHUNK]))
        chapters.append((f"Pages {i + 1}-{min(i + PAGES_PER_FALLBACK_CHUNK, len(pages))}", body))
    return chapters


def extract_chapters(path):
    """Returns (book_title, [(chapter_title, text)])."""
    doc = fitz.open(path)
    title = (doc.metadata or {}).get("title") or ""
    pages = _strip_headers_footers(_page_texts(doc))
    chapters = _split_by_toc(doc, pages) or _split_by_headings(pages) or _split_by_pages(pages)
    doc.close()
    chapters = [(t, body) for t, body in chapters if len(body) >= MIN_CHAPTER_CHARS]
    chapters = strip_front_matter(chapters)
    if not chapters:
        raise ValueError("no extractable text — scanned/image PDF?")
    return title, chapters
