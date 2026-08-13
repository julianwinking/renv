"""Admin config listing: paths match the repo tree, not a flat tab list."""

from __future__ import annotations

from renv import web
from renv.research import db


def test_config_listing_paths_match_disk_layout(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    rows = web._config_listing(tmp_path, con, "p")
    by = {(r["scope"], r["name"]): r["path"] for r in rows}
    assert by[("env", "AGENTS.md")] == "AGENTS.md"
    assert by[("project", "AGENTS.md")] == "projects/p/AGENTS.md"
    assert by[("writing", "style.md")] == "templates/writing/style.md"
    assert by[("template", "text/paper.tex")] == "templates/project/text/paper.tex"
    assert by[("template", "AGENTS.md")] == "templates/project/AGENTS.md"
    assert "path" in rows[0]


def test_spa_shell_for_md_deep_link(tmp_path):
    """Focus segments look like filenames (`AGENTS.md`); they are app routes."""
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    db.connect(tmp_path).close()
    web.Handler.root = str(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        html = urllib.request.urlopen(base + "/p/instructions/AGENTS.md").read()
        assert b"<html" in html.lower() or b"<!doctype" in html.lower() or b"root" in html
        try:
            urllib.request.urlopen(base + "/assets/missing-bundle.js")
            raise AssertionError("missing asset should 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
            body = json.loads(e.read())
            assert body.get("error") == "not found"
    finally:
        httpd.shutdown()
