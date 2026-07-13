"""Knowledge-base full-text search (FTS5 with LIKE fallback)."""

from __future__ import annotations

from reref import claim, db, ingest, log, search


def _seed(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    ingest.add_paper(con, {"title": "Enabling LLMs to Generate Text with Citations",
                           "authors": ["Gao"], "year": 2023}, key="gao2023_alce")
    log.add_entry(con, "p", "decision", "Anchor at sentence granularity for stability")
    log.add_note(con, "p", "met advisor about telephone-effect citation drift")
    claim.add_claim(con, "p", "Span anchoring beats paper-level citation", kind="thesis")
    return con


def test_search_finds_across_kinds(tmp_path):
    con = _seed(tmp_path)
    # paper title
    hits = search.search(con, "citations")
    assert any(h["kind"] == "paper" for h in hits)
    # log entry prose
    assert any(h["kind"] == "log" for h in search.search(con, "sentence granularity"))
    # note prose
    assert any(h["kind"] == "note" for h in search.search(con, "advisor"))
    # claim text
    assert any(h["kind"] == "claim" for h in search.search(con, "anchoring"))


def test_search_project_scope(tmp_path):
    con = _seed(tmp_path)
    db.ensure_project(con, "other")
    log.add_entry(con, "other", "decision", "unrelated sentence about widgets")
    hits = search.search(con, "sentence", project="p")
    assert all(h["project"] in ("", "p") for h in hits)
    assert not any("widgets" in (h["snippet"] or "") for h in hits)


def test_search_empty_query(tmp_path):
    con = _seed(tmp_path)
    assert search.search(con, "   ") == []


def test_search_handles_special_chars(tmp_path):
    con = _seed(tmp_path)
    # must not raise on FTS operator characters
    search.search(con, 'citation(s) "drift" AND OR')
