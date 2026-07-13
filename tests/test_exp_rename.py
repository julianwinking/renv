"""Renaming an experiment slug (safe: links are by integer id, not slug)."""

from __future__ import annotations

import pytest

from reref import db, experiment, log


def _con(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    return con


def test_rename_slug_keeps_links(tmp_path):
    con = _con(tmp_path)
    experiment.create_experiment(con, "p", "001-old", title="T")
    e = tmp_path / "e.py"
    e.write_text("import json,os\njson.dump({'m':1.0},"
                 "open(os.environ['REREF_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "p", "001-old", entrypoint=str(e), root=str(tmp_path))
    log.add_entry(con, "p", "result", "r", experiment="001-old", runs=[run["id"]])

    got = experiment.update_meta(con, "p", "001-old", new_slug="001-new", title="T2")
    assert got["slug"] == "001-new" and got["title"] == "T2"
    # the run still belongs to the (renamed) experiment — linked by id
    assert experiment.list_runs(con, got["id"])[0]["id"] == run["id"]
    assert experiment.get_experiment(con, "p", "001-old") is None


def test_rename_rejects_dupe_and_bad(tmp_path):
    con = _con(tmp_path)
    experiment.create_experiment(con, "p", "001-a")
    experiment.create_experiment(con, "p", "002-b")
    with pytest.raises(ValueError):                     # collides with existing
        experiment.update_meta(con, "p", "002-b", new_slug="001-a")
    with pytest.raises(ValueError):                     # invalid slug
        experiment.update_meta(con, "p", "002-b", new_slug="Bad Slug!")
