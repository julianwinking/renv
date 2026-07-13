"""The committed project template + `reref new` instantiation."""

from __future__ import annotations

import shutil
from pathlib import Path

from reref import authoring, db

REPO = Path(__file__).resolve().parent.parent


def _seed_template(corpus):
    """Copy the repo's committed template into a throwaway corpus root."""
    shutil.copytree(REPO / "templates", corpus / "templates")


def test_repo_ships_a_tracked_template():
    tmpl = REPO / "templates" / "project"
    assert (tmpl / "ideation.md").exists()
    assert (tmpl / "text" / "paper.tex").exists()
    assert (tmpl / "gitignore").exists()           # renamed to .gitignore on instantiate
    assert (tmpl / "src" / "run.py").exists()


def test_scaffold_from_template_substitutes_and_renames(tmp_path):
    _seed_template(tmp_path)
    db.connect(tmp_path)
    authoring.scaffold_from_template(tmp_path, "myproj", "My Great Paper")
    dest = tmp_path / "projects" / "myproj"

    assert (dest / "ideation.md").read_text().startswith("# My Great Paper")
    assert "{{title}}" not in (dest / "text" / "paper.tex").read_text()
    assert "My Great Paper" in (dest / "text" / "paper.tex").read_text()
    # gitignore -> .gitignore, and the literal 'gitignore' file is not copied
    assert (dest / ".gitignore").exists()
    assert not (dest / "gitignore").exists()
    # engine-sourced preamble is written
    assert r"\newcommand{\spancite}" in (dest / "text" / "preamble.tex").read_text()


def test_scaffold_is_idempotent(tmp_path):
    _seed_template(tmp_path)
    db.connect(tmp_path)
    authoring.scaffold_from_template(tmp_path, "p", "Title")
    (tmp_path / "projects" / "p" / "ideation.md").write_text("EDITED")
    authoring.scaffold_from_template(tmp_path, "p", "Title")  # must not clobber
    assert (tmp_path / "projects" / "p" / "ideation.md").read_text() == "EDITED"


def test_fallback_without_template(tmp_path):
    db.connect(tmp_path)  # no templates/ dir in this corpus
    authoring.scaffold_from_template(tmp_path, "p", "Title")
    dest = tmp_path / "projects" / "p"
    assert (dest / "ideation.md").exists() and (dest / "text" / "paper.tex").exists()
