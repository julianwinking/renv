"""The decision/reasoning log — Pillar 5's prose half, with the §0 invariant.

Every entry is typed (decision / hypothesis / observation / result / blocker) and
may carry evidence links to runs and citations. The anti-hallucination rule is
enforced here, at the write boundary: a ``result`` entry must cite at least one
``run`` — a measured outcome cannot be asserted without a reproducible source.
``check_invariants`` re-audits the whole DB so that any raw-SQL backdoor write is
still caught.
"""

from __future__ import annotations

import sqlite3

from .db import now, project_id, row_to_dict

ENTRY_TYPES = ("decision", "hypothesis", "observation", "result", "blocker")


def add_entry(
    con: sqlite3.Connection,
    project: str,
    type: str,
    body_md: str,
    *,
    experiment: str | None = None,
    runs: list[int] | None = None,
    citations: list[int] | None = None,
) -> dict:
    """Append a log entry. Raises ValueError if a ``result`` has no run evidence."""
    if type not in ENTRY_TYPES:
        raise ValueError(f"type must be one of {ENTRY_TYPES}, got {type!r}")
    runs = runs or []
    citations = citations or []
    if type == "result" and not runs:
        raise ValueError(
            "a 'result' entry must link at least one run (--evidence run:<id>); "
            "measured numbers may only come from a recorded run"
        )

    pid = project_id(con, project)
    experiment_id = None
    if experiment:
        erow = con.execute(
            "SELECT id FROM experiment WHERE project_id=? AND slug=?", (pid, experiment)
        ).fetchone()
        if not erow:
            raise KeyError(f"experiment {experiment!r} not found in {project!r}")
        experiment_id = erow["id"]

    # a result's run evidence must be a real, *done* run of *this* project — not a
    # failed run, nor one from another project (else the §0 guarantee is hollow)
    for run_id in runs:
        r = con.execute(
            "SELECT e.project_id, r.status FROM run r "
            "JOIN experiment e ON e.id=r.experiment_id WHERE r.id=?", (run_id,)
        ).fetchone()
        if not r:
            raise ValueError(f"run {run_id} does not exist")
        if r["project_id"] != pid:
            raise ValueError(f"run {run_id} belongs to another project")
        if r["status"] != "done":
            raise ValueError(f"run {run_id} is {r['status']!r}, not a completed run")

    cur = con.execute(
        "INSERT INTO log_entry (project_id, experiment_id, type, ts, body_md) "
        "VALUES (?,?,?,?,?)",
        (pid, experiment_id, type, now(), body_md),
    )
    entry_id = cur.lastrowid
    for run_id in runs:
        con.execute(
            "INSERT INTO log_evidence (log_entry_id, run_id) VALUES (?,?)",
            (entry_id, run_id),
        )
    for cite_id in citations:
        con.execute(
            "INSERT INTO log_evidence (log_entry_id, citation_id) VALUES (?,?)",
            (entry_id, cite_id),
        )
    con.commit()
    return row_to_dict(
        con.execute("SELECT * FROM log_entry WHERE id=?", (entry_id,)).fetchone()
    )


def list_entries(con: sqlite3.Connection, project: str, *, limit: int = 50) -> list[dict]:
    pid = project_id(con, project)
    rows = con.execute(
        "SELECT * FROM log_entry WHERE project_id=? ORDER BY id DESC LIMIT ?",
        (pid, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        ev = con.execute(
            "SELECT run_id, citation_id FROM log_evidence WHERE log_entry_id=?", (r["id"],)
        ).fetchall()
        d["evidence"] = {
            "runs": [e["run_id"] for e in ev if e["run_id"] is not None],
            "citations": [e["citation_id"] for e in ev if e["citation_id"] is not None],
        }
        out.append(d)
    return out


def add_note(
    con: sqlite3.Connection, project: str, body_md: str, *, title: str | None = None
) -> dict:
    pid = project_id(con, project)
    cur = con.execute(
        "INSERT INTO note (project_id, ts, title, body_md) VALUES (?,?,?,?)",
        (pid, now(), title, body_md),
    )
    con.commit()
    return row_to_dict(con.execute("SELECT * FROM note WHERE id=?", (cur.lastrowid,)).fetchone())


def check_invariants(con: sqlite3.Connection) -> list[dict]:
    """Audit the whole DB for §0 violations. Empty list == clean."""
    violations = []
    rows = con.execute(
        "SELECT le.id, le.project_id FROM log_entry le "
        "WHERE le.type='result' AND NOT EXISTS ("
        "  SELECT 1 FROM log_evidence ev WHERE ev.log_entry_id=le.id AND ev.run_id IS NOT NULL)"
    ).fetchall()
    for r in rows:
        violations.append({
            "kind": "result_without_run",
            "log_entry_id": r["id"],
            "detail": "a 'result' entry has no run evidence",
        })
    return violations
