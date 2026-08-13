"""Manuscript write API — files, weave, compile, span-cite — over the live server."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from renv import web
from renv.research import authoring, db, manuscript


def _start(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    authoring.scaffold_paper(tmp_path / "projects" / "p", "p", "P")
    con.close()
    web.Handler.root = str(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


def _get(base, path):
    return json.loads(urllib.request.urlopen(base + path).read())


def _post(base, path, body):
    req = urllib.request.Request(
        base + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def test_write_tree_read_write_roundtrip(tmp_path):
    httpd, base = _start(tmp_path)
    try:
        tree = _get(base, "/api/write/p/tree")
        names = {n["name"] for n in tree["tree"]}
        assert "paper.tex" in names and "preamble.tex" in names
        paper = _get(base, "/api/write/p/file?path=paper.tex")
        assert r"\spancite" in paper["content"] or r"\bibliography" in paper["content"]
        saved = _post(base, "/api/write/p/file",
                      {"path": "sections/intro.tex", "content": r"\section{Intro}"})
        assert saved["saved"] == "sections/intro.tex"
        got = _get(base, "/api/write/p/file?path=sections/intro.tex")
        assert got["content"] == r"\section{Intro}"
        # weave outputs cannot be overwritten through the API
        try:
            _post(base, "/api/write/p/file",
                  {"path": "results_table.tex", "content": "nope"})
            raise AssertionError("weave file was writable")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        ctx = _get(base, "/api/write/p/context")
        assert "spancites" in ctx and "metrics" in ctx
    finally:
        httpd.shutdown()


def test_write_path_traversal_rejected(tmp_path):
    httpd, base = _start(tmp_path)
    try:
        try:
            _get(base, "/api/write/p/file?path=../AGENTS.md")
            raise AssertionError
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        httpd.shutdown()


def test_compile_without_engine_returns_hint(tmp_path, monkeypatch):
    httpd, base = _start(tmp_path)
    monkeypatch.setattr(manuscript, "detect_engine", lambda which=None: None)
    try:
        res = _post(base, "/api/write/p/compile", {"weave": True})
        assert res["ok"] is False
        assert "latexmk" in res["tried"]
        assert res["woven"]  # weave still ran
    finally:
        httpd.shutdown()


def test_dispatch_tables_are_the_api_surface():
    # AGENTS.md #10: routes live in tables, not an if-chain
    assert "/api/overview" in web.GET_EXACT
    assert any(spec == ("api", "write", "*", "tree") for spec, _ in web.GET_STAR)
    assert "/api/claim" in web.POST_EXACT
    assert any(spec == ("api", "write", "*", "cite") for spec, _ in web.POST_STAR)