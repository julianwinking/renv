"""Property-based tests for the parsers that real-world PDFs broke three times
in one week (bracketed vs dotted styles, column scrambles, marker ranges).
Deterministic (derandomize) so CI stays reproducible; the win over example
tests is input breadth, not randomness."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from renv.papers import bibliography as bib
from renv.papers.ingest import parse_bibtex

DET = settings(derandomize=True, max_examples=75)

words = st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=6, max_size=40).map(
    lambda s: " ".join(s.split())).filter(lambda s: len(s) >= 5)


@DET
@given(st.integers(min_value=3, max_value=40), words, st.booleans())
def test_numbered_lists_fully_recovered(k, title, dotted):
    anchor = (lambda i: f"{i}.") if dotted else (lambda i: f"[{i}]")
    entries = "\n".join(
        f"{anchor(i)} Author {chr(65 + i % 26)}. {title} variant {i}. Venue, 20{i % 30:02d}."
        for i in range(1, k + 1))
    text = f"Introduction prose without any markers.\n\nReferences\n\n{entries}\n"
    sec, got = bib.split_reference_entries(text)
    assert [e["num"] for e in got] == list(range(1, k + 1))
    assert all(e["raw"] and e["start"] < e["end"] for e in got)


@DET
@given(st.lists(st.integers(min_value=1, max_value=60), min_size=1, max_size=6,
                unique=True), st.integers(min_value=1, max_value=60))
def test_markers_extract_exactly_the_valid_numbers(nums, maxvalid):
    valid = set(range(1, maxvalid + 1))
    text = f"as shown in [{', '.join(map(str, nums))}] recently."
    found = bib.find_markers(text, valid)
    expected = [n for n in nums if n in valid]
    assert ([m for f in found for m in f["nums"]] == expected) if expected else not found


@DET
@given(st.integers(min_value=1, max_value=50), st.integers(min_value=1, max_value=50))
def test_marker_ranges_expand(a, b):
    lo, hi = min(a, b), max(a, b)
    found = bib.find_markers(f"see [{lo}-{hi}] and [{lo}–{hi}].", set(range(1, 51)))
    assert all(f["nums"] == list(range(lo, hi + 1)) for f in found) and len(found) == 2


@DET
@given(st.text(max_size=3000))
def test_parsers_never_crash_on_arbitrary_text(text):
    sec, entries = bib.split_reference_entries(text)
    assert isinstance(entries, list)
    for e in entries:
        assert isinstance(e["num"], int) and e["start"] <= e["end"]
    bib.find_markers(text, set(range(1, 40)))
    assert isinstance(parse_bibtex(text), list)


@DET
@given(st.from_regex(r"[a-z]{3,9}[0-9]{0,4}", fullmatch=True), words, words)
def test_bibtex_fields_roundtrip(key, title, author):
    entry = f"@article{{{key},\n  title = {{{title}}},\n  author = \"{author}\",\n  year = 2026\n}}"
    parsed = parse_bibtex(entry)
    assert len(parsed) == 1 and parsed[0]["bibkey"] == key
    assert parsed[0]["fields"]["title"] == title
    assert parsed[0]["fields"]["year"] == "2026"
