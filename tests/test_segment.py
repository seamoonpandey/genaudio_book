import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from extract import HEADING_RE, clean_text, _split_by_headings


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


if __name__ == "__main__":
    test_heading_regex(); test_clean_text(); test_split_by_headings()
    print("ok")
