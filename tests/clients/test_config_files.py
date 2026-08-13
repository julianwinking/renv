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
