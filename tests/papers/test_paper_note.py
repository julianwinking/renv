"""Span-anchored paper notes — domain + agent CLI + graph membership."""

from __future__ import annotations

import argparse

import pytest

from renv.cli import cmd_annotate_add, cmd_annotate_list, cmd_claim_test
from renv.papers import ingest, paper_note
from renv.research import claim, db, experiment, search
from renv.web import _graph


def _seed(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    ingest.add_paper(con, {"title": "ALCE", "authors": ["Gao"], "year": 2023},
                     key="gao2023_alce")
    return con


def test_add_note_requires_quote(tmp_path):
    con = _seed(tmp_path)
    with pytest.raises(ValueError):
        paper_note.add_note(con, "gao2023_alce", "p", quote="  ", body="x")


def test_add_note_joins_project_graph(tmp_path):
    con = _seed(tmp_path)
    n = paper_note.add_note(
        con, "gao2023_alce", "p",
        quote="ALCE evaluates citation quality along two axes.",
        body="Headline metric axes — recall vs precision.",
        kind="note", color="teal")
    assert n["id"] and n["kind"] == "note"
    g = _graph(con, str(tmp_path), "p")
    ids = {node["id"] for node in g["nodes"]}
    assert f"pnote:{n['id']}" in ids
    assert any(node["kind"] == "paper" for node in g["nodes"])
    assert any(e["kind"] == "annotates" and e["target"] == f"pnote:{n['id']}"
               for e in g["edges"])


def test_search_finds_paper_notes(tmp_path):
    con = _seed(tmp_path)
    paper_note.add_note(
        con, "gao2023_alce", "p",
        quote="Citation recall measures whether the set of cited passages together entail",
        body="Use this as the gold definition of recall.")
    hits = search.search(con, "entail", project="p")
    assert any(h["kind"] == "pnote" for h in hits)


def test_cli_annotate_add_and_list(tmp_path, capsys):
    _seed(tmp_path)
    cmd_annotate_add(argparse.Namespace(
        corpus=str(tmp_path), paper="gao2023_alce", project="p",
        quote="Unlike commercial search assistants that cite an entire web page",
        body="Granularity of the cite is the product.", kind="note",
        color="amber", page=1))
    out = capsys.readouterr().out
    assert "pnote #" in out and "gao2023_alce" in out
    cmd_annotate_list(argparse.Namespace(
        corpus=str(tmp_path), paper=None, project="p"))
    listed = capsys.readouterr().out
    assert "Granularity" in listed


def test_cli_claim_test_preregisters(tmp_path, capsys):
    con = _seed(tmp_path)
    experiment.create_experiment(con, "p", "001", hypothesis="h")
    c = claim.add_claim(con, "p", "lexical overlap undersells paraphrases",
                        kind="hypothesis")
    cmd_claim_test(argparse.Namespace(
        corpus=str(tmp_path), project="p", experiment="001", claim_id=c["id"]))
    assert "pre-registered" in capsys.readouterr().out
    tests = claim.list_tests(con, "p")
    assert tests and tests[0]["claim_id"] == c["id"]
    assert tests[0]["experiment_slug"] == "001"
