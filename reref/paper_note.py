"""Positional notes on a paper — the reader's marginalia, made queryable.

A note is anchored to a text span with the same W3C selector citations use
(quote + prefix/suffix, plus an optional char position), so it re-highlights
at the right place on the rendered PDF and survives small text shifts. Notes
are project-scoped: a note taken while reading is *about* the work you are
doing, so it joins that project's graph — where it can go on to motivate an
experiment, support a claim, or record how a method should be implemented.
"""

from __future__ import annotations

import sqlite3

from .db import now, project_id, row_to_dict

COLORS = ("amber", "teal", "violet", "rose", "blue", "slate")
KINDS = ("note", "question", "hypothesis")


def _paper_id(con: sqlite3.Connection, key: str) -> int:
    row = con.execute("SELECT id FROM paper WHERE key=?", (key,)).fetchone()
    if not row:
        raise KeyError(f"no paper {key!r}")
    return row["id"]


def add_note(con: sqlite3.Connection, paper_key: str, project: str | None, *,
             quote: str, body: str = "", page: int | None = None,
             prefix: str | None = None, suffix: str | None = None,
             src_start: int | None = None, src_end: int | None = None,
             color: str = "amber", kind: str = "note") -> dict:
    if not (quote or "").strip():
        raise ValueError("a paper note must anchor to a quoted span")
    if color not in COLORS:
        raise ValueError(f"color must be one of {COLORS}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    pid = _paper_id(con, paper_key)
    proj = project_id(con, project) if project else None
    cur = con.execute(
        "INSERT INTO paper_note (paper_id, project_id, page, quote, prefix, suffix, "
        "src_start, src_end, color, kind, body_md, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, proj, page, quote, prefix, suffix, src_start, src_end, color, kind, body, now()))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM paper_note WHERE id=?", (cur.lastrowid,)).fetchone())


def update_note(con: sqlite3.Connection, note_id: int, **fields) -> dict:
    row = con.execute("SELECT * FROM paper_note WHERE id=?", (note_id,)).fetchone()
    if not row:
        raise KeyError(f"no paper note #{note_id}")
    allowed = {"body_md", "color", "page", "kind"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    if fields.get("color") and fields["color"] not in COLORS:
        raise ValueError(f"color must be one of {COLORS}")
    if fields.get("kind") and fields["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    merged = {**row_to_dict(row), **fields}
    con.execute(
        "UPDATE paper_note SET body_md=?, color=?, page=?, kind=?, edited=? WHERE id=?",
        (merged["body_md"], merged["color"], merged["page"], merged["kind"], now(), note_id))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM paper_note WHERE id=?", (note_id,)).fetchone())


def delete_note(con: sqlite3.Connection, note_id: int) -> None:
    if not con.execute("SELECT 1 FROM paper_note WHERE id=?", (note_id,)).fetchone():
        raise KeyError(f"no paper note #{note_id}")
    con.execute("DELETE FROM paper_note WHERE id=?", (note_id,))
    con.commit()


def list_for_paper(con: sqlite3.Connection, paper_key: str,
                   project: str | None = None) -> list[dict]:
    """Notes on a paper. Scoped to one project when given, else all projects."""
    pid = _paper_id(con, paper_key)
    if project:
        proj = project_id(con, project)
        rows = con.execute(
            "SELECT * FROM paper_note WHERE paper_id=? AND project_id=? "
            "ORDER BY page, src_start, id", (pid, proj))
    else:
        rows = con.execute(
            "SELECT * FROM paper_note WHERE paper_id=? ORDER BY page, src_start, id", (pid,))
    return [row_to_dict(r) for r in rows]


def list_for_project(con: sqlite3.Connection, project: str) -> list[dict]:
    """Every paper note taken in a project, with the paper's key — the raw
    material for the project graph's paper-note nodes."""
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT n.*, p.key AS paper_key, p.title AS paper_title "
        "FROM paper_note n JOIN paper p ON p.id=n.paper_id "
        "WHERE n.project_id=? ORDER BY n.id", (pid,))]
