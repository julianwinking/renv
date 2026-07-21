"""Round-1 hardening from the adversarial reviews: runner, §0, ingest, refs."""

from __future__ import annotations

import pytest

from renv.papers import ingest
from renv.research import db, experiment, log, refs
from renv.research.dataset import register_dataset


def _exp(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    experiment.create_experiment(con, "p", "001")
    return con


# --- runner robustness (code-review #1/#2/#3) --------------------------------
def test_timeout_marks_failed_and_frees_experiment(tmp_path):
    con = _exp(tmp_path)
    slow = tmp_path / "slow.py"; slow.write_text("import time; time.sleep(5)\n")
    with pytest.raises(RuntimeError):
        experiment.run_experiment(con, "p", "001", entrypoint=str(slow),
                                  root=str(tmp_path), timeout=1)
    assert con.execute("SELECT status FROM run ORDER BY id DESC LIMIT 1").fetchone()["status"] == "failed"
    # experiment is freed (not stuck 'running')
    assert experiment.get_experiment(con, "p", "001")["status"] == "planned"


def test_malformed_metrics_marks_failed_not_running(tmp_path):
    con = _exp(tmp_path)
    bad = tmp_path / "bad.py"
    bad.write_text("import os\nopen(os.environ['RENV_RUN_DIR']+'/metrics.json','w').write('not json')\n")
    with pytest.raises(RuntimeError):
        experiment.run_experiment(con, "p", "001", entrypoint=str(bad), root=str(tmp_path))
    assert con.execute("SELECT status FROM run ORDER BY id DESC LIMIT 1").fetchone()["status"] == "failed"


def test_nonscalar_metric_rejected(tmp_path):
    con = _exp(tmp_path)
    bad = tmp_path / "b.py"
    bad.write_text("import json,os\njson.dump({'x':[1,2]}, open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    with pytest.raises(RuntimeError):
        experiment.run_experiment(con, "p", "001", entrypoint=str(bad), root=str(tmp_path))


def test_run_records_provenance_grade(tmp_path):
    con = _exp(tmp_path)
    good = tmp_path / "g.py"
    good.write_text("import json,os\njson.dump({'r':0.5}, open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "p", "001", entrypoint=str(good), root=str(tmp_path))
    # no git/dataset in tmp -> graded degraded, entrypoint hash captured
    assert run["provenance"] == "degraded"
    assert run["entrypoint_sha"]


# --- §0: a result's run must be a done run of the same project (code #5) ------
def test_result_rejects_failed_or_foreign_run(tmp_path):
    con = _exp(tmp_path)
    db.ensure_project(con, "other")
    experiment.create_experiment(con, "other", "x")
    good = tmp_path / "g.py"
    good.write_text("import json,os\njson.dump({'r':0.5}, open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "other", "x", entrypoint=str(good), root=str(tmp_path))
    # the done run belongs to 'other', so logging a result in 'p' against it is rejected
    with pytest.raises(ValueError):
        log.add_entry(con, "p", "result", "claim", runs=[run["id"]])


# --- ingest hardening (code #7/#8/#10) ---------------------------------------
def test_safe_xml_rejects_entities():
    with pytest.raises(ValueError):
        ingest._safe_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><feed/>')


def test_dataset_reregister_changed_bytes_rejected(tmp_path):
    con = db.connect(tmp_path)
    a = tmp_path / "d.jsonl"; a.write_text("v1\n")
    register_dataset(con, "ds", path=str(a))
    a.write_text("v2-different\n")
    with pytest.raises(ValueError):
        register_dataset(con, "ds", path=str(a))


# --- code↔store reference convention -----------------------------------------
def test_refs_scan_and_strip(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(
        "def fix():\n"
        "    # @renv:finding:42:fixes  guard malformed metrics.json\n"
        "    return 1  # @renv:paper:gao2023_alce  ALCE metric\n")
    found = refs.scan(tmp_path)
    kinds = {(r["kind"], r["id"], r["relation"]) for r in found}
    assert ("finding", "42", "fixes") in kinds
    assert ("paper", "gao2023_alce", None) in kinds

    stripped = refs.strip_text(f.read_text())
    assert "@renv" not in stripped
    assert "return 1" in stripped                    # code survives
    assert "    # @renv:finding" not in stripped     # pure-tag comment line dropped


def test_refs_validate_flags_dangling(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    experiment.create_experiment(con, "p", "001")
    refs_list = [{"kind": "experiment", "id": "001"}, {"kind": "finding", "id": "999"}]
    out = refs.validate(con, refs_list)
    assert out[0]["resolves"] is True and out[1]["resolves"] is False


# --- secrets withheld from the runner (review: env leak) ---------------------
def test_secret_env_withheld_unless_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("HARMLESS_VAR", "ok")
    con = _exp(tmp_path)
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json,os\n"
        "json.dump({'has_secret': 1.0 if os.environ.get('OPENAI_API_KEY') else 0.0,\n"
        "           'has_harmless': 1.0 if os.environ.get('HARMLESS_VAR') else 0.0},\n"
        "          open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "p", "001", entrypoint=str(probe), root=str(tmp_path))
    m = {x["name"]: x["value"] for x in experiment.get_metrics(con, run["id"])}
    assert m["has_secret"] == 0.0       # withheld by default
    assert m["has_harmless"] == 1.0     # normal vars pass through

    experiment.create_experiment(con, "p", "002")
    run2 = experiment.run_experiment(con, "p", "002", entrypoint=str(probe),
                                     root=str(tmp_path), env_allow=["OPENAI_API_KEY"])
    m2 = {x["name"]: x["value"] for x in experiment.get_metrics(con, run2["id"])}
    assert m2["has_secret"] == 1.0      # opted back in
