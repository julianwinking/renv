"""Background (async) runs so a long job doesn't block the single-threaded server."""

from __future__ import annotations

import time

from renv.research import db, experiment


def _setup(tmp_path, body):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    experiment.create_experiment(con, "p", "001")
    entry = tmp_path / "e.py"
    entry.write_text(body)
    return con, str(entry)


def test_start_run_returns_immediately_then_completes(tmp_path):
    con, entry = _setup(
        tmp_path,
        "import json,os,time\ntime.sleep(0.4)\n"
        "json.dump({'r':0.5}, open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    started = experiment.start_run(con, "p", "001", entrypoint=entry, root=str(tmp_path))
    assert started["status"] == "running" and started["async"] is True
    rid = started["run_id"]
    # immediately after, still running (returned before the sleep finished)
    assert experiment.run_status(con, rid)["status"] == "running"
    # poll until done
    for _ in range(50):
        if experiment.run_status(con, rid)["status"] == "done":
            break
        time.sleep(0.1)
    final = experiment.run_status(con, rid)
    assert final["status"] == "done"
    assert {m["name"]: m["value"] for m in final["metrics"]}["r"] == 0.5


def test_async_failure_is_recorded(tmp_path):
    con, entry = _setup(tmp_path, "import sys; sys.exit(3)\n")
    rid = experiment.start_run(con, "p", "001", entrypoint=entry, root=str(tmp_path))["run_id"]
    for _ in range(50):
        if experiment.run_status(con, rid)["status"] != "running":
            break
        time.sleep(0.1)
    assert experiment.run_status(con, rid)["status"] == "failed"
    assert experiment.get_experiment(con, "p", "001")["status"] == "planned"
