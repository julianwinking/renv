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

from .db import now, project_id, row_to_dict

KINDS = ("thesis", "contribution", "assertion")
STANCES = ("supports", "refutes")


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
                  note: str | None = None) -> dict:
    """Attach a citation or run as evidence; re-derive the claim's status."""
    if stance not in STANCES:
        raise ValueError(f"stance must be supports/refutes, got {stance!r}")
    if citation_id is None and run_id is None:
        raise ValueError("evidence needs a citation_id or a run_id")
    if not con.execute("SELECT 1 FROM claim WHERE id=?", (claim_id,)).fetchone():
        raise KeyError(f"no claim #{claim_id}")
    if citation_id and not con.execute(
            "SELECT 1 FROM citation WHERE id=?", (citation_id,)).fetchone():
        raise KeyError(f"no citation #{citation_id}")
    if run_id:
        r = con.execute("SELECT status FROM run WHERE id=?", (run_id,)).fetchone()
        if not r:
            raise KeyError(f"no run #{run_id}")
        if r["status"] != "done":
            raise ValueError(f"run #{run_id} is {r['status']!r}, not a completed run")
    con.execute(
        "INSERT INTO claim_evidence (claim_id, citation_id, run_id, stance, note) "
        "VALUES (?,?,?,?,?)", (claim_id, citation_id, run_id, stance, note))
    _recompute_status(con, claim_id)
    con.commit()
    return get_claim(con, claim_id)


def _recompute_status(con: sqlite3.Connection, claim_id: int) -> None:
    stances = {r["stance"] for r in con.execute(
        "SELECT stance FROM claim_evidence WHERE claim_id=?", (claim_id,)).fetchall()}
    status = ("refuted" if "refutes" in stances
              else "supported" if "supports" in stances else "open")
    con.execute("UPDATE claim SET status=? WHERE id=?", (status, claim_id))


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
    """Edit a claim's wording. Status stays derived from evidence — only the
    prose changes, so an inline rename never touches what backs it."""
    if not text.strip():
        raise ValueError("claim text must not be empty")
    if not con.execute("SELECT 1 FROM claim WHERE id=?", (claim_id,)).fetchone():
        raise KeyError(f"no claim #{claim_id}")
    con.execute("UPDATE claim SET text=? WHERE id=?", (text.strip(), claim_id))
    con.commit()
    return get_claim(con, claim_id)


def get_claim(con: sqlite3.Connection, claim_id: int) -> dict | None:
    c = row_to_dict(con.execute("SELECT * FROM claim WHERE id=?", (claim_id,)).fetchone())
    if not c:
        return None
    c["evidence"] = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM claim_evidence WHERE claim_id=? ORDER BY id", (claim_id,)).fetchall()]
    c["relations"] = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM claim_relation WHERE claim_id=? ORDER BY id", (claim_id,)).fetchall()]
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
            "SELECT COUNT(*) n FROM claim_evidence WHERE claim_id=?", (c["id"],)).fetchone()["n"]
    return rows
