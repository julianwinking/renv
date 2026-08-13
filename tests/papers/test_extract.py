"""Structured card extraction, including the empty-card / --all CLI path."""

from __future__ import annotations

import argparse

from renv.cli import cmd_extract
from renv.papers import extract, ingest
from renv.research import db


def test_extract_all_empty_card_is_not_skipped(tmp_path):
    """A paper whose cues miss every field is a successful empty card, not skipped."""
    con = db.connect(tmp_path)
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "thin.txt").write_text("hello world only stop words.\n")
    ingest.add_paper(con, {"title": "Thin"}, key="thin")
    out = extract.extract_all(con, tmp_path)
    assert "thin" in out and "skipped" not in out["thin"]
    assert out["thin"] == {}


def test_extract_all_missing_file_is_skipped(tmp_path):
    con = db.connect(tmp_path)
    (tmp_path / "library").mkdir()
    ingest.add_paper(con, {"title": "Ghost"}, key="ghost")
    out = extract.extract_all(con, tmp_path)
    assert out["ghost"] == {"skipped": "no source file"}


def test_cmd_extract_all_empty_card_does_not_crash(tmp_path, capsys):
    """Regression: `renv extract --all` used card['skipped'] whenever n==0."""
    con = db.connect(tmp_path)
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "thin.txt").write_text("hello world only stop words.\n")
    ingest.add_paper(con, {"title": "Thin"}, key="thin")
    ingest.add_paper(con, {"title": "Ghost"}, key="ghost")
    cmd_extract(argparse.Namespace(corpus=str(tmp_path), all=True, key=None))
    out = capsys.readouterr().out
    assert "thin: 0 field(s)" in out
    assert "ghost: 0 field(s)  (no source file)" in out
