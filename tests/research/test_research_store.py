"""Phase A: the SQLite research store — DB, experiments/runs, decision log.

Dependency-free; each test gets a throwaway env root via tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from renv.research import db, experiment, log
from renv.research.dataset import register_dataset


# --- db.py -------------------------------------------------------------------
def test_connect_creates_and_migrates(tmp_path):
    con = db.connect(tmp_path)
    assert db.db_path(tmp_path).exists()
    assert db.schema_version(con) == len(db.MIGRATIONS)
    # every declared table exists
    names = {r["name"] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(db.TABLES) <= names


def test_migrate_is_idempotent(tmp_path):
    db.connect(tmp_path).close()
    con = db.connect(tmp_path)  # second open must not re-run migrations
    assert db.schema_version(con) == len(db.MIGRATIONS)


def test_foreign_keys_enforced(tmp_path):
    import sqlite3
    con = db.connect(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO experiment (project_id, slug, created) "
                    "VALUES (999, 'x', 'now')")
        con.commit()


def test_config_dedup_by_hash(tmp_path):
    con = db.connect(tmp_path)
    a = db.get_or_create_config(con, {"lr": 0.1, "k": 5})
    b = db.get_or_create_config(con, {"k": 5, "lr": 0.1})  # key order irrelevant
    c = db.get_or_create_config(con, {"lr": 0.2, "k": 5})
    assert a == b and a != c


def test_export_is_deterministic(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    out1 = (db.export(con, tmp_path) / "project.jsonl").read_text()
    out2 = (db.export(con, tmp_path) / "project.jsonl").read_text()
    assert out1 == out2
    assert json.loads(out1.splitlines()[0])["slug"] == "p"


# --- experiment.py: the DAG + reproducible runner ----------------------------
def test_experiment_dag(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    experiment.create_experiment(con, "proj", "001-base", title="baseline")
    child = experiment.create_experiment(
        con, "proj", "002-tweak", title="tweak", parent="001-base")
    assert child["parent_id"] is not None
    rows = experiment.list_experiments(con, "proj")
    assert [r["slug"] for r in rows] == ["001-base", "002-tweak"]


def test_create_experiment_unknown_parent_raises(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    with pytest.raises(KeyError):
        experiment.create_experiment(con, "proj", "x", parent="nope")


def _write_entrypoint(tmp_path) -> Path:
    """An entrypoint honoring the runner contract: read params, write metrics."""
    script = tmp_path / "entry.py"
    script.write_text(
        "import json, os\n"
        "d = os.environ['RENV_RUN_DIR']\n"
        "p = json.loads(os.environ['RENV_PARAMS'])\n"
        "json.dump({'recall': p.get('k', 0) / 10}, open(d + '/metrics.json', 'w'))\n"
        "open(d + '/figure.txt', 'w').write('plot')\n"
    )
    return script


def test_run_records_metrics_and_artifacts(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    experiment.create_experiment(con, "proj", "001-base")
    entry = _write_entrypoint(tmp_path)

    run = experiment.run_experiment(
        con, "proj", "001-base", entrypoint=str(entry), root=str(tmp_path),
        params={"k": 8}, seed=3)

    assert run["status"] == "done" and run["seed"] == 3
    metrics = {m["name"]: m["value"] for m in experiment.get_metrics(con, run["id"])}
    assert metrics["recall"] == pytest.approx(0.8)
    arts = con.execute("SELECT path FROM artifact WHERE run_id=?", (run["id"],)).fetchall()
    assert any("figure.txt" in a["path"] for a in arts)
    # metrics.json/stdout/stderr are not counted as artifacts
    assert not any("metrics.json" in a["path"] for a in arts)
    # experiment flipped to done; latest_metrics surfaces for the progress view
    assert experiment.get_experiment(con, "proj", "001-base")["status"] == "done"


def test_failing_run_is_recorded_then_raised(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    experiment.create_experiment(con, "proj", "001-base")
    bad = tmp_path / "bad.py"
    bad.write_text("import sys; sys.exit(2)\n")

    with pytest.raises(RuntimeError):
        experiment.run_experiment(con, "proj", "001-base",
                                  entrypoint=str(bad), root=str(tmp_path))
    status = con.execute("SELECT status FROM run ORDER BY id DESC LIMIT 1").fetchone()
    assert status["status"] == "failed"


def test_run_pins_dataset(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    experiment.create_experiment(con, "proj", "001-base")
    data = tmp_path / "eval.jsonl"
    data.write_text('{"q": 1}\n')
    ds = register_dataset(con, "evalset", path=str(data), description="demo")
    assert ds["sha256"]
    run = experiment.run_experiment(
        con, "proj", "001-base", entrypoint=str(_write_entrypoint(tmp_path)),
        root=str(tmp_path), params={"k": 5}, dataset_id=ds["id"])
    assert run["dataset_id"] == ds["id"]


# --- log.py: the §0 anti-hallucination invariant -----------------------------
def test_decision_entry_ok(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    e = log.add_entry(con, "proj", "decision", "## Use sentence anchors\nbecause…")
    assert e["type"] == "decision"


def test_result_without_run_is_rejected(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    with pytest.raises(ValueError):
        log.add_entry(con, "proj", "result", "recall hit 0.8")


def test_result_with_run_is_accepted_and_linked(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "proj")
    experiment.create_experiment(con, "proj", "001-base")
    run = experiment.run_experiment(
        con, "proj", "001-base", entrypoint=str(_write_entrypoint(tmp_path)),
        root=str(tmp_path), params={"k": 8})
    e = log.add_entry(con, "proj", "result", "recall hit 0.8", runs=[run["id"]])
    entries = log.list_entries(con, "proj")
    linked = next(x for x in entries if x["id"] == e["id"])
    assert linked["evidence"]["runs"] == [run["id"]]


def test_check_invariants_catches_raw_sql_backdoor(tmp_path):
    con = db.connect(tmp_path)
    pid = db.ensure_project(con, "proj")
    # bypass the write boundary to simulate a bad direct write
    con.execute("INSERT INTO log_entry (project_id, type, ts, body_md) "
                "VALUES (?, 'result', 'now', 'snuck in')", (pid,))
    con.commit()
    violations = log.check_invariants(con)
    assert violations and violations[0]["kind"] == "result_without_run"
