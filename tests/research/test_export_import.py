"""Export is round-trippable (importer) and project-scoped."""

from __future__ import annotations

import json

from renv.research import claim, db, experiment, log


def _seed(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "a", title="A")
    db.ensure_project(con, "b", title="B")
    experiment.create_experiment(con, "a", "001", hypothesis="h")
    entry = tmp_path / "e.py"
    entry.write_text("import json,os\njson.dump({'r':0.5},open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "a", "001", entrypoint=str(entry), root=str(tmp_path))
    log.add_entry(con, "a", "result", "recall 0.5", runs=[run["id"]])
    claim.add_claim(con, "a", "thesis claim", kind="thesis")
    experiment.create_experiment(con, "b", "001", hypothesis="other")
    return con, run


def test_export_import_roundtrip(tmp_path, tmp_path_factory):
    con, _ = _seed(tmp_path)
    db.export(con, tmp_path)

    # rebuild into a fresh, empty env from the JSONL export
    dest = tmp_path_factory.mktemp("restored")
    (dest / ".research").mkdir(parents=True)
    # copy the export dir over
    import shutil
    shutil.copytree(tmp_path / ".research" / "export", dest / ".research" / "export")
    con2 = db.connect(dest)
    n = db.import_jsonl(con2, dest)
    assert n > 0
    assert [r["slug"] for r in con2.execute("SELECT slug FROM project ORDER BY slug")] == ["a", "b"]
    assert con2.execute("SELECT COUNT(*) n FROM metric").fetchone()["n"] == 1
    assert con2.execute("SELECT text FROM claim").fetchone()["text"] == "thesis claim"
    # the §0 evidence link survived
    assert con2.execute("SELECT COUNT(*) n FROM log_evidence").fetchone()["n"] == 1


def test_project_scoped_export(tmp_path):
    con, _ = _seed(tmp_path)
    out = db.export(con, tmp_path, project="a")
    projects = [json.loads(l)["slug"]
                for l in (out / "project.jsonl").read_text().splitlines()]
    assert projects == ["a"]                       # only project a in the slice
    exps = [json.loads(l) for l in (out / "experiment.jsonl").read_text().splitlines()]
    assert all(e["project_id"] == db.project_id(con, "a") for e in exps)
    # global corpus tables are still included (papers/datasets), project rows filtered
    assert (out / "paper.jsonl").exists()
