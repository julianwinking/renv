"""The claim/evidence graph — assertions traced to citations and runs.

This wires the previously-reserved ``claim`` + ``claim_evidence`` tables into a
live backbone: every thesis / contribution / assertion you make is a node, and you
attach evidence to it — a verified *citation* (the literature supports it) or a
recorded *run* (you measured it), each with a stance (supports / refutes). A
claim's status is **derived** from its evidence (refuted > supported > open), not
hand-set, so "is this claim backed?" is a query, not an opinion. Pillar 8's review
flags any thesis/contribution claim still ``open``.
"""

from __future__ import annotations

import sqlite3

from renv.research.db import now, project_id, row_to_dict

KINDS = ("thesis", "contribution", "assertion", "hypothesis")
STANCES = ("supports", "refutes", "inconclusive")
GRADES = ("anecdotal", "suggestive", "confirmatory")


def add_claim(con: sqlite3.Connection, project: str, text: str, *,
              kind: str = "assertion", manuscript_loc: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    pid = project_id(con, project)
    cur = con.execute(
        "INSERT INTO claim (project_id, text, kind, manuscript_loc, status, created) "
        "VALUES (?,?,?,?, 'open', ?)", (pid, text, kind, manuscript_loc, now()))
    con.commit()
    return get_claim(con, cur.lastrowid)


def link_evidence(con: sqlite3.Connection, claim_id: int, *, citation_id: int | None = None,
                  run_id: int | None = None, stance: str = "supports",
                  grade: str = "suggestive", note: str | None = None) -> dict:
    """Attach a citation or run as evidence; re-derive the claim's status.

    Two honesty gates live here, at the write boundary:
    - a citation whose verifier verdict is ``none`` cannot be attached as
      *supports* — the span does not entail the claim, so it is not support;
    - run evidence records ``preregistered``: was this claim declared (via
      ``declare_test``) as tested by the run's experiment before linking?
      Undeclared evidence is exploratory (post-hoc) and lint reports it.
    """
    if stance not in STANCES:
        raise ValueError(f"stance must be one of {STANCES}, got {stance!r}")
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}, got {grade!r}")
    if citation_id is None and run_id is None:
        raise ValueError("evidence needs a citation_id or a run_id")
    if not con.execute("SELECT 1 FROM claim WHERE id=?", (claim_id,)).fetchone():
        raise KeyError(f"no claim #{claim_id}")
    preregistered = 0
    if citation_id:
        c = con.execute("SELECT support, retracted FROM citation WHERE id=?",
                        (citation_id,)).fetchone()
        if not c:
            raise KeyError(f"no citation #{citation_id}")
        if c["retracted"]:
            raise ValueError(f"citation #{citation_id} is retracted — it cannot back a claim")
        if stance == "supports" and c["support"] == "none":
            raise ValueError(
                f"citation #{citation_id}'s verifier verdict is 'none' — the cited span "
                "does not entail the claim, so it cannot be attached as support; "
                "re-verify with a better span or attach it as context instead")
    if run_id:
        r = con.execute("SELECT status, experiment_id FROM run WHERE id=?", (run_id,)).fetchone()
        if not r:
            raise KeyError(f"no run #{run_id}")
        if r["status"] != "done":
            raise ValueError(f"run #{run_id} is {r['status']!r}, not a completed run")
        preregistered = 1 if con.execute(
            "SELECT 1 FROM experiment_test WHERE experiment_id=? AND claim_id=?",
            (r["experiment_id"], claim_id)).fetchone() else 0
    con.execute(
        "INSERT INTO claim_evidence (claim_id, citation_id, run_id, stance, grade, "
        "preregistered, note, created) VALUES (?,?,?,?,?,?,?,?)",
        (claim_id, citation_id, run_id, stance, grade, preregistered, note, now()))
    _recompute_status(con, claim_id)
    con.commit()
    return get_claim(con, claim_id)


def _recompute_status(con: sqlite3.Connection, claim_id: int) -> None:
    """Derive status from LIVE evidence only — retracted rows are history, not
    proof, and 'inconclusive' is recorded but moves nothing."""
    stances = {r["stance"] for r in con.execute(
        "SELECT stance FROM claim_evidence WHERE claim_id=? AND retracted IS NULL",
        (claim_id,)).fetchall()}
    status = ("refuted" if "refutes" in stances
              else "supported" if "supports" in stances else "open")
    con.execute("UPDATE claim SET status=? WHERE id=?", (status, claim_id))


def retract_evidence(con: sqlite3.Connection, evidence_id: int, reason: str,
                     *, superseded_by: int | None = None) -> dict:
    """Retract an evidence link (bad run, wrong span, superseded result).

    The row is kept — retraction is history, not deletion — but it stops
    counting toward the claim's derived status. Reason is required so a future
    reader knows why the record went dark.
    """
    if not (reason or "").strip():
        raise ValueError("retraction requires a reason (future readers must see why)")
    row = con.execute("SELECT * FROM claim_evidence WHERE id=?", (evidence_id,)).fetchone()
    if not row:
        raise KeyError(f"no evidence #{evidence_id}")
    if row["retracted"]:
        raise ValueError(f"evidence #{evidence_id} is already retracted")
    if superseded_by is not None:
        s = con.execute("SELECT claim_id FROM claim_evidence WHERE id=?",
                        (superseded_by,)).fetchone()
        if not s:
            raise KeyError(f"no evidence #{superseded_by}")
        if s["claim_id"] != row["claim_id"]:
            raise ValueError("superseding evidence must belong to the same claim")
    con.execute(
        "UPDATE claim_evidence SET retracted=?, retract_reason=?, superseded_by=? "
        "WHERE id=?", (now(), reason.strip(), superseded_by, evidence_id))
    _recompute_status(con, row["claim_id"])
    con.commit()
    return get_claim(con, row["claim_id"])


def confirm_evidence(con: sqlite3.Connection, evidence_id: int) -> dict:
    """Clear the stale flag after re-checking that the evidence still backs the
    claim's (edited) wording."""
    row = con.execute("SELECT claim_id FROM claim_evidence WHERE id=?",
                      (evidence_id,)).fetchone()
    if not row:
        raise KeyError(f"no evidence #{evidence_id}")
    con.execute("UPDATE claim_evidence SET stale=0 WHERE id=?", (evidence_id,))
    con.commit()
    return get_claim(con, row["claim_id"])


def declare_test(con: sqlite3.Connection, project: str, experiment_slug: str,
                 claim_id: int) -> dict:
    """Pre-register: experiment ``tests`` claim, declared BEFORE evidence.

    Evidence later linked from this experiment's runs to this claim counts as
    preregistered; evidence to undeclared claims is exploratory. Declaring is
    idempotent and does not retroactively bless evidence already attached.
    """
    pid = project_id(con, project)
    e = con.execute("SELECT id FROM experiment WHERE project_id=? AND slug=?",
                    (pid, experiment_slug)).fetchone()
    if not e:
        raise KeyError(f"experiment {experiment_slug!r} not found in {project!r}")
    c = con.execute("SELECT project_id FROM claim WHERE id=?", (claim_id,)).fetchone()
    if not c:
        raise KeyError(f"no claim #{claim_id}")
    if c["project_id"] != pid:
        raise ValueError(f"claim #{claim_id} belongs to another project")
    con.execute(
        "INSERT OR IGNORE INTO experiment_test (experiment_id, claim_id, created) "
        "VALUES (?,?,?)", (e["id"], claim_id, now()))
    con.commit()
    return get_claim(con, claim_id)


def undeclare_test(con: sqlite3.Connection, test_id: int) -> None:
    if not con.execute("SELECT 1 FROM experiment_test WHERE id=?", (test_id,)).fetchone():
        raise KeyError(f"no test declaration #{test_id}")
    con.execute("DELETE FROM experiment_test WHERE id=?", (test_id,))
    con.commit()


def list_tests(con: sqlite3.Connection, project: str) -> list[dict]:
    """All test declarations of a project (experiment ``tests`` claim edges)."""
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT t.*, e.slug AS experiment_slug FROM experiment_test t "
        "JOIN experiment e ON e.id=t.experiment_id WHERE e.project_id=? "
        "ORDER BY t.id", (pid,)).fetchall()]


def relate(con: sqlite3.Connection, claim_id: int, related_id: int,
           kind: str = "depends_on", note: str | None = None) -> dict:
    """Link two claims into a chain of argument (depends_on / contradicts).

    Structure, not proof: relations never change a claim's derived status —
    only citation/run evidence does.
    """
    if kind not in ("depends_on", "contradicts"):
        raise ValueError(f"kind must be depends_on/contradicts, got {kind!r}")
    if claim_id == related_id:
        raise ValueError("a claim cannot relate to itself")
    for cid in (claim_id, related_id):
        if not con.execute("SELECT 1 FROM claim WHERE id=?", (cid,)).fetchone():
            raise KeyError(f"no claim #{cid}")
    # walk depends_on ancestry to refuse cycles (chains must stay acyclic)
    if kind == "depends_on":
        frontier, seen = {related_id}, set()
        while frontier:
            nxt = frontier.pop()
            if nxt == claim_id:
                raise ValueError(f"relation would create a cycle (#{claim_id} ⇄ #{related_id})")
            if nxt in seen:
                continue
            seen.add(nxt)
            frontier.update(r["related_id"] for r in con.execute(
                "SELECT related_id FROM claim_relation WHERE claim_id=? AND kind='depends_on'",
                (nxt,)).fetchall())
    con.execute(
        "INSERT OR IGNORE INTO claim_relation (claim_id, related_id, kind, note) "
        "VALUES (?,?,?,?)", (claim_id, related_id, kind, note))
    con.commit()
    return get_claim(con, claim_id)


def list_relations(con: sqlite3.Connection, project: str) -> list[dict]:
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT cr.* FROM claim_relation cr JOIN claim c ON c.id=cr.claim_id "
        "WHERE c.project_id=? ORDER BY cr.id", (pid,)).fetchall()]


def update_text(con: sqlite3.Connection, claim_id: int, text: str) -> dict:
    """Edit a claim's wording. The prose IS the claim: any live evidence is
    marked stale, because what supported the old wording may not support the
    new one. Re-confirm (or retract) each stale link; lint reports the rest."""
    if not text.strip():
        raise ValueError("claim text must not be empty")
    row = con.execute("SELECT text FROM claim WHERE id=?", (claim_id,)).fetchone()
    if not row:
        raise KeyError(f"no claim #{claim_id}")
    if text.strip() != row["text"]:
        con.execute("UPDATE claim SET text=? WHERE id=?", (text.strip(), claim_id))
        con.execute("UPDATE claim_evidence SET stale=1 WHERE claim_id=? "
                    "AND retracted IS NULL", (claim_id,))
    con.commit()
    return get_claim(con, claim_id)


def delete_relation(con: sqlite3.Connection, relation_id: int) -> None:
    """Remove a claim→claim relation (argument structure is editable; evidence
    is not — evidence gets retracted, never deleted)."""
    if not con.execute("SELECT 1 FROM claim_relation WHERE id=?", (relation_id,)).fetchone():
        raise KeyError(f"no claim relation #{relation_id}")
    con.execute("DELETE FROM claim_relation WHERE id=?", (relation_id,))
    con.commit()


def get_claim(con: sqlite3.Connection, claim_id: int) -> dict | None:
    c = row_to_dict(con.execute("SELECT * FROM claim WHERE id=?", (claim_id,)).fetchone())
    if not c:
        return None
    c["evidence"] = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM claim_evidence WHERE claim_id=? ORDER BY id", (claim_id,)).fetchall()]
    c["relations"] = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM claim_relation WHERE claim_id=? ORDER BY id", (claim_id,)).fetchall()]
    c["related_from"] = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM claim_relation WHERE related_id=? ORDER BY id", (claim_id,)).fetchall()]
    c["tests"] = [row_to_dict(r) for r in con.execute(
        "SELECT t.*, e.slug AS experiment_slug FROM experiment_test t "
        "JOIN experiment e ON e.id=t.experiment_id WHERE t.claim_id=? "
        "ORDER BY t.id", (claim_id,)).fetchall()]
    return c


def list_claims(con: sqlite3.Connection, project: str, *, status: str | None = None) -> list[dict]:
    pid = project_id(con, project)
    sql, params = "SELECT * FROM claim WHERE project_id=?", [pid]
    if status:
        sql += " AND status=?"
        params.append(status)
    rows = [row_to_dict(r) for r in con.execute(sql + " ORDER BY id", params).fetchall()]
    for c in rows:
        c["evidence_count"] = con.execute(
            "SELECT COUNT(*) n FROM claim_evidence WHERE claim_id=? "
            "AND retracted IS NULL", (c["id"],)).fetchone()["n"]
    return rows
