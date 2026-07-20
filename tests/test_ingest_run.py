"""Cluster runs: ingesting results whose compute/data never touched this machine."""

from __future__ import annotations

import json

import pytest

from renv import db, experiment, log
from renv.dataset import register_dataset


def _exp(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    experiment.create_experiment(con, "p", "010-cluster", hypothesis="h")
    return con


def test_ingest_copied_run_dir_with_provenance(tmp_path):
    con = _exp(tmp_path)
    rd = tmp_path / "copied-run"
    rd.mkdir()
    (rd / "metrics.json").write_text(json.dumps({"acc": 0.91, "loss": 0.2}))
    (rd / "curve.json").write_text("[1,2]")
    (rd / "provenance.json").write_text(json.dumps(
        {"git_sha": "abc123", "seed": 7, "params": {"lr": 0.1}}))
    run = experiment.ingest_run(con, "p", "010-cluster", run_dir=rd)
    assert run["status"] == "done" and run["provenance"] == "remote-verified"
    assert run["git_sha"] == "abc123" and run["seed"] == 7
    assert run["config_id"] is not None       # params from the wrapper became a config
    names = {m["name"] for m in experiment.get_metrics(con, run["id"])}
    assert names == {"acc", "loss"}
    arts = [r["path"] for r in con.execute(
        "SELECT path FROM artifact WHERE run_id=?", (run["id"],))]
    assert any("curve.json" in p for p in arts)
    assert not any("provenance.json" in p for p in arts)   # bookkeeping, not artifact
    # §0: the ingested run backs results like any local run
    e = log.add_entry(con, "p", "result", "acc 0.91 on cluster", runs=[run["id"]])
    assert e["id"]


def test_ingest_remote_only_metrics(tmp_path):
    con = _exp(tmp_path)
    run = experiment.ingest_run(
        con, "p", "010-cluster", metrics={"acc": 0.88},
        remote="ssh://cluster/scratch/julian/runs/exp42")
    assert run["provenance"] == "remote" and run["remote"].startswith("ssh://")
    art = con.execute("SELECT * FROM artifact WHERE run_id=?", (run["id"],)).fetchone()
    assert art["kind"] == "remote" and art["path"].startswith("ssh://")


def test_ingest_rejects_bad_input(tmp_path):
    con = _exp(tmp_path)
    with pytest.raises(ValueError):          # neither dir nor metrics
        experiment.ingest_run(con, "p", "010-cluster")
    with pytest.raises(KeyError):            # unknown experiment
        experiment.ingest_run(con, "p", "nope", metrics={"a": 1})
    with pytest.raises(ValueError):          # non-numeric metric → no run row left
        experiment.ingest_run(con, "p", "010-cluster", metrics={"acc": "high"})
    assert con.execute("SELECT COUNT(*) n FROM run").fetchone()["n"] == 0


def test_remote_registry_and_locator_expansion(tmp_path):
    from renv import remote
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    experiment.create_experiment(con, "p", "010-cluster")
    r = remote.add_remote(con, "snaga", data_root="/scratch/julian/research",
                          description="uni cluster")
    assert r["host"] == "snaga"                      # defaults to the name (ssh alias)
    # shorthand locators expand against the data root
    run = experiment.ingest_run(con, "p", "010-cluster",
                                metrics={"acc": 0.9}, remote="snaga:runs/exp42")
    assert run["remote"] == "snaga:/scratch/julian/research/runs/exp42"
    ds = register_dataset(con, "in100", location="snaga:data/in100",
                          sha256="ab" * 32)
    assert ds["location"] == "snaga:/scratch/julian/research/data/in100"
    # absolute / unknown-prefix locators pass through untouched
    assert remote.expand_locator(con, "/local/path") == "/local/path"
    assert remote.expand_locator(con, "elsewhere:runs/x") == "elsewhere:runs/x"
    with pytest.raises(ValueError):
        remote.add_remote(con, "Bad Name!")


def test_remote_dataset_registration(tmp_path):
    con = db.connect(tmp_path)
    ds = register_dataset(con, "imagenet-subset", location="ssh://cluster/data/in100",
                          sha256="deadbeef" * 8)
    assert ds["location"].startswith("ssh://") and ds["sha256"].startswith("deadbeef")
    with pytest.raises(ValueError):          # same version, different bytes → refused
        register_dataset(con, "imagenet-subset", location="ssh://cluster/data/in100",
                         sha256="feedface" * 8)
