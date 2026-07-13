"""Project planning — phases and milestones on a time axis (the Gantt view).

A plan item is *intent*, not evidence: "what should be done until when"
(conference deadlines, submission phases, work blocks). It is deliberately
decoupled from claims/log entries — §0 governs facts, not intentions — which
is also why items may be edited and deleted freely. Stored status is only
``planned``/``done``; whether something is *active* or *overdue* is derived
from its dates by whoever renders it.
"""

from __future__ import annotations

import re
import sqlite3

from .db import now, project_id, row_to_dict

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_date(value: str | None, field: str, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required (YYYY-MM-DD)")
        return
    if not _DATE.match(value):
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}")


def add_item(con: sqlite3.Connection, project: str, title: str, *,
             due: str, kind: str = "phase", start: str | None = None,
             note: str | None = None) -> dict:
    if kind not in ("phase", "milestone"):
        raise ValueError(f"kind must be phase|milestone, got {kind!r}")
    if not title.strip():
        raise ValueError("title must not be empty")
    _check_date(due, "due", required=True)
    _check_date(start, "start")
    if kind == "milestone":
        start = None
    elif start and start > due:
        raise ValueError(f"start {start} is after due {due}")
    pid = project_id(con, project)
    cur = con.execute(
        "INSERT INTO plan_item (project_id, title, kind, start, due, note, created) "
        "VALUES (?,?,?,?,?,?,?)", (pid, title.strip(), kind, start, due, note, now()))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM plan_item WHERE id=?", (cur.lastrowid,)).fetchone())


def update_item(con: sqlite3.Connection, item_id: int, **fields) -> dict:
    """Update title/start/due/status/note. Plans are mutable by design."""
    row = con.execute("SELECT * FROM plan_item WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise KeyError(f"no plan item #{item_id}")
    allowed = {"title", "start", "due", "status", "note"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    if "status" in fields and fields["status"] not in ("planned", "done"):
        raise ValueError("status must be planned|done")
    _check_date(fields.get("due"), "due")
    _check_date(fields.get("start"), "start")
    merged = {**row_to_dict(row), **{k: v for k, v in fields.items() if v is not None
                                     or k in ("start", "note")}}
    if merged["kind"] == "phase" and merged["start"] and merged["start"] > merged["due"]:
        raise ValueError(f"start {merged['start']} is after due {merged['due']}")
    con.execute(
        "UPDATE plan_item SET title=?, start=?, due=?, status=?, note=?, edited=? "
        "WHERE id=?",
        (merged["title"], merged["start"] if merged["kind"] == "phase" else None,
         merged["due"], merged["status"], merged["note"], now(), item_id))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM plan_item WHERE id=?", (item_id,)).fetchone())


def delete_item(con: sqlite3.Connection, item_id: int) -> None:
    if not con.execute("SELECT 1 FROM plan_item WHERE id=?", (item_id,)).fetchone():
        raise KeyError(f"no plan item #{item_id}")
    con.execute("DELETE FROM plan_item WHERE id=?", (item_id,))
    con.commit()


def list_items(con: sqlite3.Connection, project: str) -> list[dict]:
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT * FROM plan_item WHERE project_id=? "
        "ORDER BY COALESCE(start, due), due, id", (pid,))]
