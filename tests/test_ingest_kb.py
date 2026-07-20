"""Phase D: ingest (Pillar 1) + structured extraction & usage map (Pillar 2).

Network is injected (`get=`), so these run offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reref import db, extract, ingest

REPO = Path(__file__).resolve().parent.parent

ARXIV_ATOM = (
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
    "<title>Enabling Large Language Models to Generate Text with Citations</title>"
    "<published>2023-05-23T00:00:00Z</published>"
    "<summary>We propose ALCE, a benchmark for citation.</summary>"
    "<author><name>Tianyu Gao</name></author>"
    "<author><name>Howard Yen</name></author>"
    "</entry></feed>"
).encode()

CROSSREF_JSON = json.dumps({"message": {
    "title": ["The Telephone Effect"],
    "author": [{"given": "An", "family": "Chen"}],
    "published": {"date-parts": [[2025, 6, 1]]},
    "container-title": ["ACL"], "DOI": "10.1/abc", "URL": "https://doi.org/10.1/abc",
}}).encode()


# --- source detection --------------------------------------------------------
def test_detect_classifies_sources(tmp_path):
    f = tmp_path / "x.txt"; f.write_text("hi")
    assert ingest.detect(str(f)) == ("file", str(f))
    assert ingest.detect("2305.14627") == ("arxiv", "2305.14627")
    assert ingest.detect("arxiv.org/abs/2409.02897") == ("arxiv", "2409.02897")
    assert ingest.detect("10.18653/v1/2023.emnlp-main.398")[0] == "doi"
    with pytest.raises(ValueError):
        ingest.detect("just some words")


# --- metadata parsers (offline) ----------------------------------------------
def test_fetch_arxiv_parses_atom():
    meta = ingest.fetch_arxiv("2305.14627", get=lambda url, **k: ARXIV_ATOM)
    assert meta["authors"] == ["Tianyu Gao", "Howard Yen"]
    assert meta["year"] == 2023 and meta["arxiv"] == "2305.14627"
    assert ingest.derive_key(meta) == "gao2023_alce" or ingest.derive_key(meta).startswith("gao2023")


def test_fetch_crossref_parses_json():
    meta = ingest.fetch_crossref("10.1/abc", get=lambda url, **k: CROSSREF_JSON)
    assert meta["year"] == 2025 and meta["venue"] == "ACL"
    assert meta["authors"] == ["An Chen"]


# --- add upserts a paper row -------------------------------------------------
def test_add_arxiv_upserts_paper(tmp_path):
    con = db.connect(tmp_path)
    res = ingest.add(con, tmp_path, "2305.14627", get=lambda url, **k: ARXIV_ATOM)
    assert res["kind"] == "arxiv"
    papers = ingest.list_papers(con)
    assert len(papers) == 1 and papers[0]["year"] == 2023
    # idempotent upsert: same key, no duplicate
    ingest.add(con, tmp_path, "2305.14627", get=lambda url, **k: ARXIV_ATOM)
    assert len(ingest.list_papers(con)) == 1


def test_add_file_lands_in_library(tmp_path):
    con = db.connect(tmp_path)
    src = tmp_path / "mypaper.txt"; src.write_text("a paper about citations")
    res = ingest.add(con, tmp_path, str(src))
    assert res["reindex"] is True
    assert (tmp_path / "library" / "mypaper.txt").exists()
    assert ingest.list_papers(con)[0]["sha256"]


# --- structured extraction on the real demo corpus ---------------------------
def test_extract_card_from_demo_paper(tmp_path):
    con = db.connect(tmp_path)
    # copy a real demo paper into this env's library and register it
    text = (REPO / "library" / "gao2023_alce.txt").read_text()
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "gao2023_alce.txt").write_text(text)
    ingest.add_paper(con, {"title": "ALCE", "authors": ["Gao"], "year": 2023},
                     key="gao2023_alce")

    card = extract.extract_card(con, tmp_path, "gao2023_alce")
    assert card  # at least some fields found
    for field, v in card.items():
        assert v["text"] and "start" in v["anchor"] and "end" in v["anchor"]
        # the anchor offsets actually point at the quoted text in the source
        assert text[v["anchor"]["start"]:v["anchor"]["end"]] == v["anchor"]["quote"]
    # persisted + reloadable
    assert extract.get_card(con, "gao2023_alce").keys() == card.keys()


# --- the citation usage map (reverse index) ----------------------------------
def test_paper_usage_reverse_index(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "span")
    ingest.add_paper(con, {"title": "ALCE", "authors": ["Gao"], "year": 2023},
                     key="gao2023_alce")

    class _Cit:  # minimal stand-in for a Citation
        source_id = "gao2023_alce"; claim = "citation precision uses NLI"
        start, end = 427, 577; quote = "Citation precision …"; prefix = suffix = ""
        support = "full"; support_score = 1.0

    row = ingest.record_citation(con, "span", _Cit(), manuscript_loc="Intro:p2")
    assert row["paper_id"]
    usage = ingest.paper_usage(con, "gao2023_alce")
    assert len(usage["cited_in"]) == 1
    assert usage["cited_in"][0]["project"] == "span"
    assert usage["cited_in"][0]["manuscript_loc"] == "Intro:p2"


def test_citations_json_is_derived_from_table(tmp_path):
    """The citation table is the single source of truth; the sidecar is a view."""
    con = db.connect(tmp_path)
    db.ensure_project(con, "span")

    class _Cit:
        source_id = "gao2023_alce"; claim = "NLI flags unsupported"; start, end = 427, 577
        quote = "Citation precision…"; prefix = suffix = ""; support = "full"; support_score = 1.0

    ingest.record_citation(con, "span", _Cit())
    root = tmp_path / "projects" / "span"
    out = ingest.regenerate_sidecar(con, "span", root)
    data = json.loads(out.read_text())
    assert len(data) == 1
    assert data[0]["source_id"] == "gao2023_alce" and data[0]["support"] == "full"
