"""Experiments, configs, runs, metrics — Pillar 5's relational core.

An experiment is a node in a per-project DAG (``parent_id`` is the edge): one
experiment answers one question. Running it produces a ``run`` that pins the full
reproduction tuple, plus ``metric`` rows — the sole home of every number that may
later appear in the paper.

The runner executes an entrypoint as a subprocess in a fresh run directory. The
contract is language-agnostic: the child reads ``RENV_RUN_DIR`` and
``RENV_PARAMS`` (JSON) from the environment and writes ``metrics.json`` (a flat
``{name: value}`` map) plus any artifact files into ``RENV_RUN_DIR``. We ingest
those back into the DB. Numbers thus enter the system only via a recorded run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Env vars matching this are withheld from experiment subprocesses by default, so a
# child can't read or accidentally print secrets into the archived stdout. Opt a
# specific one back in with env_allow=[...] (e.g. an API key a run genuinely needs).
_SECRET_RE = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.I)


def _child_env(run_dir, params, seed, env_allow):
    allow = set(env_allow or [])
    env = {k: v for k, v in os.environ.items()
           if k in allow or not _SECRET_RE.search(k)}
    env.update({"RENV_RUN_DIR": str(run_dir), "RENV_PARAMS": json.dumps(params),
                "RENV_SEED": str(seed)})
    return env

import sqlite3

from .config import CONFIG_FILENAME, sha256_file
from .db import get_or_create_config, now, project_id, row_to_dict


# --- reproduction tuple capture (all best-effort) ----------------------------
def _git_sha(root) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root),
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def _git_dirty(root) -> bool | None:
    """True if the working tree has uncommitted changes (so the SHA is a lie)."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(root),
            capture_output=True, text=True, timeout=5,
        )
        return bool(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:
        return None


def _env_hash(root) -> str | None:
    """Hash of the locked environment (uv.lock) so a run records its deps."""
    lock = Path(root) / "uv.lock"
    return sha256_file(lock) if lock.exists() else None


def _corpus_lock_hash(root) -> str | None:
    """Fingerprint of the corpus index config the run retrieved against."""
    lock = Path(root) / ".renv" / CONFIG_FILENAME
    if not lock.exists():
        return None
    try:
        return json.loads(lock.read_text()).get("config_fingerprint")
    except Exception:
        return None


# --- experiments (the DAG) ---------------------------------------------------
def create_experiment(
    con: sqlite3.Connection,
    project: str,
    slug: str,
    *,
    title: str | None = None,
    hypothesis: str | None = None,
    parent: str | None = None,
) -> dict:
    pid = project_id(con, project)
    parent_id = None
    if parent:
        prow = con.execute(
            "SELECT id FROM experiment WHERE project_id=? AND slug=?", (pid, parent)
        ).fetchone()
        if not prow:
            raise KeyError(f"parent experiment {parent!r} not found in {project!r}")
        parent_id = prow["id"]
    cur = con.execute(
        "INSERT INTO experiment (project_id, parent_id, slug, title, hypothesis, "
        "status, created) VALUES (?,?,?,?,?, 'planned', ?)",
        (pid, parent_id, slug, title or slug, hypothesis, now()),
    )
    con.commit()
    return get_experiment(con, project, slug)


def get_experiment(con: sqlite3.Connection, project: str, slug: str) -> dict | None:
    pid = project_id(con, project)
    return row_to_dict(
        con.execute(
            "SELECT * FROM experiment WHERE project_id=? AND slug=?", (pid, slug)
        ).fetchone()
    )


def set_status(con: sqlite3.Connection, project: str, slug: str, status: str) -> None:
    pid = project_id(con, project)
    completed = now() if status in ("done", "abandoned") else None
    con.execute(
        "UPDATE experiment SET status=?, completed=? WHERE project_id=? AND slug=?",
        (status, completed, pid, slug),
    )
    con.commit()


import re as _re
_SLUG_RE = _re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def update_meta(con: sqlite3.Connection, project: str, slug: str, *,
                title: str | None = None, hypothesis: str | None = None,
                new_slug: str | None = None) -> dict:
    """Edit an experiment's title/hypothesis, and optionally rename its slug.

    Renaming is safe: runs and log entries link by the integer id, not the
    slug — the slug is a human label (must stay unique in the project). Only
    on-disk run directories keep their old-slug names, which is cosmetic.
    """
    pid = project_id(con, project)
    row = con.execute("SELECT id FROM experiment WHERE project_id=? AND slug=?",
                      (pid, slug)).fetchone()
    if not row:
        raise KeyError(f"no experiment {slug!r} in {project!r}")
    if new_slug is not None and new_slug != slug:
        if not _SLUG_RE.match(new_slug):
            raise ValueError("slug must be lowercase letters/digits/-/_ , e.g. 004-sweep")
        if con.execute("SELECT 1 FROM experiment WHERE project_id=? AND slug=?",
                       (pid, new_slug)).fetchone():
            raise ValueError(f"experiment {new_slug!r} already exists in {project!r}")
        con.execute("UPDATE experiment SET slug=? WHERE id=?", (new_slug, row["id"]))
        slug = new_slug
    if title is not None:
        con.execute("UPDATE experiment SET title=? WHERE id=?", (title, row["id"]))
    if hypothesis is not None:
        con.execute("UPDATE experiment SET hypothesis=? WHERE id=?", (hypothesis, row["id"]))
    con.commit()
    return get_experiment(con, project, slug)


def set_parent(con: sqlite3.Connection, project: str, slug: str,
               parent: str | None) -> dict:
    """Re-parent an experiment onto the DAG (None detaches). Refuses cycles."""
    pid = project_id(con, project)
    row = con.execute("SELECT id FROM experiment WHERE project_id=? AND slug=?",
                      (pid, slug)).fetchone()
    if not row:
        raise KeyError(f"no experiment {slug!r} in {project!r}")
    parent_id = None
    if parent is not None:
        prow = con.execute("SELECT id FROM experiment WHERE project_id=? AND slug=?",
                           (pid, parent)).fetchone()
        if not prow:
            raise KeyError(f"no experiment {parent!r} in {project!r}")
        parent_id = prow["id"]
        walk = parent_id
        while walk is not None:
            if walk == row["id"]:
                raise ValueError(f"{parent!r} descends from {slug!r} — would create a cycle")
            nxt = con.execute("SELECT parent_id FROM experiment WHERE id=?", (walk,)).fetchone()
            walk = nxt["parent_id"] if nxt else None
    con.execute("UPDATE experiment SET parent_id=? WHERE id=?", (parent_id, row["id"]))
    con.commit()
    return get_experiment(con, project, slug)


def list_experiments(con: sqlite3.Connection, project: str) -> list[dict]:
    """All experiments of a project, parents before children (DAG-friendly order)."""
    pid = project_id(con, project)
    rows = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM experiment WHERE project_id=? ORDER BY id", (pid,)
    ).fetchall()]
    # attach best run metrics summary for the progress view
    for r in rows:
        r["metrics"] = latest_metrics(con, r["id"])
    return rows


def latest_metrics(con: sqlite3.Connection, experiment_id: int) -> dict:
    """Metrics from the most recent finished run of an experiment (for display)."""
    run = con.execute(
        "SELECT id FROM run WHERE experiment_id=? AND status='done' "
        "ORDER BY id DESC LIMIT 1", (experiment_id,)
    ).fetchone()
    if not run:
        return {}
    rows = con.execute(
        "SELECT name, value FROM metric WHERE run_id=?", (run["id"],)
    ).fetchall()
    return {r["name"]: r["value"] for r in rows}


# --- metric definitions (standardized display across projects) ----------------
def define_metric(con: sqlite3.Connection, name: str, *, label: str | None = None,
                  unit: str | None = None, direction: str = "maximize",
                  fmt: str = ".3f", description: str | None = None) -> dict:
    """Register (or update) how a metric NAME is rendered and compared everywhere.

    Optional by design: unregistered metrics still record and display raw —
    a run is never blocked on missing display metadata.
    """
    if direction not in ("maximize", "minimize", "info"):
        raise ValueError(f"direction must be maximize|minimize|info, got {direction!r}")
    format(0.0, fmt)  # fail fast on a bad format spec
    con.execute(
        "INSERT INTO metric_def (name, label, unit, direction, fmt, description) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET label=excluded.label, "
        "unit=excluded.unit, direction=excluded.direction, fmt=excluded.fmt, "
        "description=excluded.description",
        (name, label, unit, direction, fmt, description))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM metric_def WHERE name=?", (name,)).fetchone())


def metric_defs(con: sqlite3.Connection) -> dict[str, dict]:
    """All metric definitions, keyed by metric name."""
    return {r["name"]: row_to_dict(r)
            for r in con.execute("SELECT * FROM metric_def ORDER BY name")}


def fmt_metric(defs: dict[str, dict], name: str, value) -> str:
    """Render one metric value per its definition (fallback: 4 significant digits)."""
    if not isinstance(value, (int, float)):
        return str(value)
    d = defs.get(name)
    if not d:
        return f"{value:.4g}"
    out = format(value, d["fmt"] or ".3f")
    return f"{out}{d['unit']}" if d["unit"] else out


# --- runs (reproducible execution) -------------------------------------------
def _fail_run(con, project, slug, run_id, note: str) -> None:
    """Record a run failure and free the experiment so it can be retried."""
    con.execute("UPDATE run SET status='failed', finished=? WHERE id=?", (now(), run_id))
    set_status(con, project, slug, "planned")  # not stuck in 'running'
    con.commit()


def _begin_run(con, project, slug, *, entrypoint, root, params, dataset_id, seed):
    """Create the run row (status running) + grade provenance; return (run_id, run_dir)."""
    exp = get_experiment(con, project, slug)
    if not exp:
        raise KeyError(f"experiment {slug!r} not found in {project!r}")
    config_id = get_or_create_config(con, params)
    sha, dirty, env_h = _git_sha(root), _git_dirty(root), _env_hash(root)
    ep_sha = sha256_file(Path(entrypoint)) if Path(entrypoint).exists() else None
    complete = bool(sha) and dirty is False and bool(env_h) and dataset_id is not None

    cur = con.execute(
        "INSERT INTO run (experiment_id, config_id, dataset_id, git_sha, env_hash, "
        "corpus_lock_hash, seed, entrypoint, entrypoint_sha, dirty, provenance, "
        "status, started) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'running', ?)",
        (exp["id"], config_id, dataset_id, sha, env_h, _corpus_lock_hash(root), seed,
         str(entrypoint), ep_sha, 1 if dirty else 0,
         "complete" if complete else "degraded", now()),
    )
    run_id = cur.lastrowid
    set_status(con, project, slug, "running")
    run_dir = Path(root) / "projects" / project / "runs" / f"{slug}-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    con.commit()
    return run_id, run_dir


def _execute_run(con, root, project, slug, run_id, run_dir, *,
                 entrypoint, params, seed, env_allow, timeout):
    """Run the subprocess, ingest results, finalize the run. Raises on failure."""
    env = _child_env(run_dir, params, seed, env_allow)
    try:
        proc = subprocess.run(
            [sys.executable, str(entrypoint)], cwd=str(root), env=env,
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        _fail_run(con, project, slug, run_id, "timeout")
        raise RuntimeError(f"run {run_id} timed out after {timeout}s")

    (run_dir / "stdout.txt").write_text(proc.stdout or "")
    (run_dir / "stderr.txt").write_text(proc.stderr or "")
    if proc.returncode != 0:
        _fail_run(con, project, slug, run_id, "nonzero-exit")
        raise RuntimeError(f"run {run_id} failed (exit {proc.returncode}); see {run_dir}/stderr.txt")
    try:
        _ingest_metrics(con, run_id, run_dir)
        _ingest_artifacts(con, run_id, run_dir)
    except Exception as exc:
        _fail_run(con, project, slug, run_id, f"ingest-error: {exc}")
        raise RuntimeError(f"run {run_id} produced unreadable output: {exc}")
    con.execute("UPDATE run SET status='done', finished=? WHERE id=?", (now(), run_id))
    set_status(con, project, slug, "done")
    con.commit()


def run_experiment(con, project, slug, *, entrypoint, root=".", params=None,
                   dataset_id=None, seed=0, timeout=1800, env_allow=None) -> dict:
    """Execute an experiment synchronously; pins provenance, records failures.
    Returns the finished run row. (Blocking — fine for the CLI.)"""
    params = params or {}
    run_id, run_dir = _begin_run(con, project, slug, entrypoint=entrypoint, root=root,
                                 params=params, dataset_id=dataset_id, seed=seed)
    _execute_run(con, root, project, slug, run_id, run_dir, entrypoint=entrypoint,
                 params=params, seed=seed, env_allow=env_allow, timeout=timeout)
    return row_to_dict(con.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone())


def start_run(con, project, slug, *, entrypoint, root=".", params=None,
              dataset_id=None, seed=0, timeout=1800, env_allow=None) -> dict:
    """Launch a run in a background thread and return immediately — so a long run
    never blocks the (single-threaded) MCP server. Poll with run_status(run_id)."""
    import threading
    params = params or {}
    run_id, run_dir = _begin_run(con, project, slug, entrypoint=entrypoint, root=root,
                                 params=params, dataset_id=dataset_id, seed=seed)

    def worker():
        wcon = __import__("renv.db", fromlist=["connect"]).connect(root)
        try:
            _execute_run(wcon, root, project, slug, run_id, run_dir, entrypoint=entrypoint,
                         params=params, seed=seed, env_allow=env_allow, timeout=timeout)
        except Exception:
            pass  # failure is already recorded in the DB by _fail_run
        finally:
            wcon.close()

    threading.Thread(target=worker, daemon=True).start()
    return {"run_id": run_id, "status": "running", "async": True}


def run_status(con: sqlite3.Connection, run_id: int) -> dict:
    """Current status of a run + its metrics (poll an async run with this)."""
    run = row_to_dict(con.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone())
    if not run:
        raise KeyError(f"no run #{run_id}")
    run["metrics"] = get_metrics(con, run_id)
    return run


def _insert_metrics(con: sqlite3.Connection, run_id: int, data) -> None:
    """Validate + insert a flat metrics mapping (shared by runner and ingest)."""
    if not isinstance(data, dict) or not data:
        raise ValueError("metrics must be a non-empty JSON object {name: value}")
    for name, value in data.items():
        # accept {"name": value} or {"name": {"value": v, "split": s}}
        if isinstance(value, dict):
            v, split = value.get("value"), value.get("split")
        else:
            v, split = value, None
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"metric {name!r} value must be numeric, got {type(v).__name__}")
        con.execute(
            "INSERT INTO metric (run_id, name, value, split) VALUES (?,?,?,?)",
            (run_id, name, float(v), split),
        )


def _ingest_metrics(con: sqlite3.Connection, run_id: int, run_dir: Path) -> None:
    mfile = run_dir / "metrics.json"
    if not mfile.exists():
        return
    data = json.loads(mfile.read_text())  # raises on bad JSON -> caught by run_experiment
    _insert_metrics(con, run_id, data)


def _ingest_artifacts(con: sqlite3.Connection, run_id: int, run_dir: Path) -> None:
    reserved = {"metrics.json", "stdout.txt", "stderr.txt", "provenance.json"}
    for f in sorted(run_dir.iterdir()):
        if f.is_file() and f.name not in reserved:
            con.execute(
                "INSERT INTO artifact (run_id, path, sha256, kind) VALUES (?,?,?,?)",
                (run_id, str(f), sha256_file(f), f.suffix.lstrip(".") or None),
            )


def ingest_run(con: sqlite3.Connection, project: str, slug: str, *,
               run_dir=None, metrics: dict | None = None,
               remote: str | None = None, dataset_id: int | None = None) -> dict:
    """Register a run executed ELSEWHERE (a cluster) — the §0 entry point for
    results whose compute and data may never touch this machine.

    Two shapes:
    - ``run_dir``: a copied-back run directory (metrics.json + artifact files,
      optionally provenance.json written by the cluster-side wrapper).
    - ``metrics`` (+ ``remote`` locator): nothing local at all — the agent
      operating the cluster passes the final scalars and where the run lives
      (e.g. ``ssh://cluster/scratch/runs/exp42``); artifacts stay remote and
      are recorded as a remote artifact row.

    Provenance is graded honestly: ``remote-verified`` only when a
    provenance.json supplies at least a git_sha (plus whatever env/dataset
    fingerprints the wrapper captured); plain ``remote`` otherwise. Never
    ``complete`` — this machine did not observe the execution.
    """
    pid = project_id(con, project)
    erow = con.execute(
        "SELECT id FROM experiment WHERE project_id=? AND slug=?", (pid, slug)).fetchone()
    if not erow:
        raise KeyError(f"no experiment {slug!r} in {project!r}")
    if run_dir is None and metrics is None:
        raise ValueError("ingest needs --dir (a copied run directory) or metrics")
    if remote:
        from .remote import expand_locator
        remote = expand_locator(con, remote)   # "snaga:runs/x" → data_root expansion

    prov = {}
    if run_dir is not None:
        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            raise ValueError(f"{run_dir} is not a directory")
        pfile = run_dir / "provenance.json"
        if pfile.exists():
            prov = json.loads(pfile.read_text())
            if not isinstance(prov, dict):
                raise ValueError("provenance.json must be a JSON object")
        if metrics is None:
            mfile = run_dir / "metrics.json"
            if not mfile.exists():
                raise ValueError(f"no metrics.json in {run_dir}")
            metrics = json.loads(mfile.read_text())

    grade = "remote-verified" if prov.get("git_sha") else "remote"
    config_id = None
    if isinstance(prov.get("params"), dict) and prov["params"]:
        config_id = get_or_create_config(con, prov["params"])
    ts = now()
    cur = con.execute(
        "INSERT INTO run (experiment_id, config_id, dataset_id, git_sha, env_hash, "
        "corpus_lock_hash, seed, status, started, finished, entrypoint, "
        "entrypoint_sha, dirty, provenance, remote) "
        "VALUES (?,?,?,?,?,?,?,'done',?,?,?,?,?,?,?)",
        (erow["id"], config_id, dataset_id, prov.get("git_sha"), prov.get("env_hash"),
         None, prov.get("seed"), prov.get("started") or ts, prov.get("finished") or ts,
         prov.get("entrypoint"), prov.get("entrypoint_sha"), None, grade,
         remote or prov.get("remote")))
    run_id = cur.lastrowid
    try:
        _insert_metrics(con, run_id, metrics)
    except Exception:
        con.rollback()
        raise
    if run_dir is not None:
        _ingest_artifacts(con, run_id, run_dir)
    elif remote:
        con.execute(
            "INSERT INTO artifact (run_id, path, sha256, kind) VALUES (?,?,?,?)",
            (run_id, remote, prov.get("sha256"), "remote"))
    set_status(con, project, slug, "done")
    con.commit()
    return row_to_dict(con.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone())


def get_metrics(con: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = con.execute("SELECT * FROM metric WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    return [row_to_dict(r) for r in rows]


def list_runs(con: sqlite3.Connection, experiment_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM run WHERE experiment_id=? ORDER BY id", (experiment_id,)
    ).fetchall()
    return [row_to_dict(r) for r in rows]
