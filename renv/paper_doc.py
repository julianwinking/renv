"""Note documents — long-form markdown attached to a paper.

Where a paper_note is a single anchored highlight, a paper_doc is a whole page
of thinking about a paper: prose you write while reading, with quoted passages
cited in as markdown blockquotes. Project-scoped, freely editable (it is your
writing, not evidence), opened as its own tab in the cockpit.
"""

from __future__ import annotations

import sqlite3

from .db import now, project_id, row_to_dict


def _paper_id(con: sqlite3.Connection, key: str) -> int:
    row = con.execute("SELECT id FROM paper WHERE key=?", (key,)).fetchone()
    if not row:
        raise KeyError(f"no paper {key!r}")
    return row["id"]


def create_doc(con: sqlite3.Connection, paper_key: str, project: str | None, *,
               title: str = "Untitled note", body: str = "") -> dict:
    pid = _paper_id(con, paper_key)
    proj = project_id(con, project) if project else None
    cur = con.execute(
        "INSERT INTO paper_doc (paper_id, project_id, title, body_md, created) "
        "VALUES (?,?,?,?,?)", (pid, proj, title.strip() or "Untitled note", body, now()))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM paper_doc WHERE id=?", (cur.lastrowid,)).fetchone())


def update_doc(con: sqlite3.Connection, doc_id: int, **fields) -> dict:
    row = con.execute("SELECT * FROM paper_doc WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise KeyError(f"no paper doc #{doc_id}")
    allowed = {"title", "body_md"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    merged = {**row_to_dict(row), **fields}
    con.execute("UPDATE paper_doc SET title=?, body_md=?, edited=? WHERE id=?",
                (merged["title"] or "Untitled note", merged["body_md"], now(), doc_id))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM paper_doc WHERE id=?", (doc_id,)).fetchone())


def delete_doc(con: sqlite3.Connection, doc_id: int) -> None:
    if not con.execute("SELECT 1 FROM paper_doc WHERE id=?", (doc_id,)).fetchone():
        raise KeyError(f"no paper doc #{doc_id}")
    con.execute("DELETE FROM paper_doc WHERE id=?", (doc_id,))
    con.commit()


def get_doc(con: sqlite3.Connection, doc_id: int) -> dict:
    row = con.execute("SELECT * FROM paper_doc WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise KeyError(f"no paper doc #{doc_id}")
    return row_to_dict(row)


def list_for_paper(con: sqlite3.Connection, paper_key: str,
                   project: str | None = None) -> list[dict]:
    """Note documents on a paper (metadata only — no body — for the list)."""
    pid = _paper_id(con, paper_key)
    cols = "id, paper_id, project_id, title, created, edited"
    if project:
        proj = project_id(con, project)
        rows = con.execute(
            f"SELECT {cols} FROM paper_doc WHERE paper_id=? AND project_id=? ORDER BY id",
            (pid, proj))
    else:
        rows = con.execute(
            f"SELECT {cols} FROM paper_doc WHERE paper_id=? ORDER BY id", (pid,))
    return [row_to_dict(r) for r in rows]
