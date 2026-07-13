"""Metric definitions — standardized rendering across CLI/web (v5 migration)."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from reref import db, experiment, web


def test_define_update_and_format(tmp_path):
    con = db.connect(tmp_path)
    d = experiment.define_metric(con, "acc", label="Accuracy", direction="maximize",
                                 fmt=".3f", description="test accuracy")
    assert d["name"] == "acc" and d["direction"] == "maximize"
    # upsert: redefining updates in place, no duplicate
    experiment.define_metric(con, "acc", label="Accuracy (test)", fmt=".1%")
    defs = experiment.metric_defs(con)
    assert len([k for k in defs if k == "acc"]) == 1
    assert defs["acc"]["label"] == "Accuracy (test)"
    assert experiment.fmt_metric(defs, "acc", 0.8351) == "83.5%"
    # unit suffix
    experiment.define_metric(con, "latency", unit="ms", direction="minimize", fmt=".0f")
    defs = experiment.metric_defs(con)
    assert experiment.fmt_metric(defs, "latency", 12.34) == "12ms"
    # unregistered metric falls back to 4 significant digits — never blocks
    assert experiment.fmt_metric(defs, "drop", 0.3733333333333333) == "0.3733"
    assert experiment.fmt_metric(defs, "weird", "n/a") == "n/a"


def test_define_rejects_bad_inputs(tmp_path):
    con = db.connect(tmp_path)
    with pytest.raises(ValueError):
        experiment.define_metric(con, "x", direction="sideways")
    with pytest.raises(ValueError):
        experiment.define_metric(con, "x", fmt="not-a-format")


def test_web_endpoints_and_cors(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    experiment.create_experiment(con, "p", "001", hypothesis="h")
    entry = tmp_path / "e.py"
    entry.write_text("import json,os\njson.dump({'r':0.5},"
                     "open(os.environ['REREF_RUN_DIR']+'/metrics.json','w'))\n")
    experiment.run_experiment(con, "p", "001", entrypoint=str(entry), root=str(tmp_path))
    experiment.define_metric(con, "r", label="Recall", direction="maximize")

    web.Handler.root = str(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        defs = json.loads(urllib.request.urlopen(base + "/api/metric_defs").read())
        assert defs["r"]["label"] == "Recall"
        runs = json.loads(urllib.request.urlopen(base + "/api/project/p/runs").read())
        assert runs[0]["experiment"] == "001" and runs[0]["metrics"] == {"r": 0.5}
        ov = json.loads(urllib.request.urlopen(base + "/api/overview").read())
        assert ov["invariants"]["clean"] is True
        # CORS: a foreign origin gets NO allow-origin header; localhost dev does
        evil = urllib.request.urlopen(urllib.request.Request(
            base + "/api/overview", headers={"Origin": "https://evil.example"}))
        assert evil.headers.get("Access-Control-Allow-Origin") is None
        dev = urllib.request.urlopen(urllib.request.Request(
            base + "/api/overview", headers={"Origin": "http://localhost:5173"}))
        assert dev.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    finally:
        httpd.shutdown()
