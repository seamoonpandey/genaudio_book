import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from extract import HEADING_RE, clean_text, strip_front_matter, _split_by_headings


def test_heading_regex():
    for good in ["Chapter 1", "CHAPTER VII", "Chapter 12: The End", "Part 2", "III", "7."]:
        assert HEADING_RE.match(good), good
    for bad in ["He walked into the room.", "chapter after chapter of misery"]:
        assert not HEADING_RE.match(bad), bad


def test_clean_text():
    raw = "The quick brown fox jum-\nped over the lazy\ndog.\n\nNew paragraph."
    out = clean_text(raw)
    assert "jumped" in out
    assert "lazy dog." in out
    assert "\n\n" in out  # paragraph break preserved


def test_split_by_headings():
    pages = [
        "Chapter 1\n" + ("First chapter sentence goes here. " * 20),
        "Chapter 2\n" + ("Second chapter sentence goes here. " * 20),
    ]
    chapters = _split_by_headings(pages)
    assert [t for t, _ in chapters] == ["Chapter 1", "Chapter 2"]
    assert "First chapter" in chapters[0][1]
    assert "Second chapter" in chapters[1][1]


def test_strip_front_matter():
    body = "Real chapter content here. " * 100  # > MIN_MAIN_CHARS
    chapters = [
        ("Title Page", "The Great Novel by A. Writer"),
        ("Contents", "Chapter 1 .... 3\nChapter 2 .... 27"),
        ("Acknowledgements", "Thanks to everyone. " * 100),
        ("Epigraph", "A short quote."),
        ("Chapter 1", body),
        ("Chapter 2", body),
        ("A Note on Sources", body),  # not junk-titled, mid-book, long: kept
    ]
    out = strip_front_matter(chapters)
    assert [t for t, _ in out] == ["Chapter 1", "Chapter 2", "A Note on Sources"]


def test_strip_front_matter_never_empties():
    only_short = [("Poem I", "short"), ("Poem II", "also short")]
    assert len(strip_front_matter(only_short)) >= 1
    all_junk = [("Contents", "x"), ("Index", "y")]
    assert strip_front_matter(all_junk) == all_junk  # fallback: keep original


if __name__ == "__main__":
    test_heading_regex(); test_clean_text(); test_split_by_headings()
    test_strip_front_matter(); test_strip_front_matter_never_empties()
    print("ok")
