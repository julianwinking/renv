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

from renv.research.db import now, project_id, row_to_dict

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
             note: str | None = None, end_deadline: bool = False,
             prepared: bool = False, parent_id: int | None = None) -> dict:
    if kind not in ("phase", "milestone", "deadline"):
        raise ValueError(f"kind must be phase|milestone|deadline, got {kind!r}")
    if not title.strip():
        raise ValueError("title must not be empty")
    _check_date(due, "due", required=True)
    _check_date(start, "start")
    if kind != "phase":
        start = None
        end_deadline = False
    elif start and start > due:
        raise ValueError(f"start {start} is after due {due}")
    if prepared and not (kind == "deadline" or end_deadline):
        raise ValueError("prepared only applies to deadlines (standalone or a phase's end)")
    pid = project_id(con, project)
    if parent_id is not None:
        prow = con.execute("SELECT * FROM plan_item WHERE id=?", (parent_id,)).fetchone()
        if not prow:
            raise KeyError(f"no plan item #{parent_id}")
        if prow["project_id"] != pid:
            raise ValueError(f"plan item #{parent_id} belongs to another project")
        if prow["kind"] != "phase":
            raise ValueError("only phases can contain sub-items")
        if prow["parent_id"]:
            raise ValueError("sub-items nest one level only")
    cur = con.execute(
        "INSERT INTO plan_item (project_id, title, kind, start, due, note, "
        "end_deadline, prepared, created, parent_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (pid, title.strip(), kind, start, due, note,
         int(end_deadline), int(prepared), now(), parent_id))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM plan_item WHERE id=?", (cur.lastrowid,)).fetchone())


def update_item(con: sqlite3.Connection, item_id: int, **fields) -> dict:
    """Update title/start/due/status/note. Plans are mutable by design."""
    row = con.execute("SELECT * FROM plan_item WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise KeyError(f"no plan item #{item_id}")
    allowed = {"title", "start", "due", "status", "note", "prepared", "end_deadline"}
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
    if merged["kind"] != "phase":
        merged["end_deadline"] = 0
    con.execute(
        "UPDATE plan_item SET title=?, start=?, due=?, status=?, note=?, "
        "prepared=?, end_deadline=?, edited=? WHERE id=?",
        (merged["title"], merged["start"] if merged["kind"] == "phase" else None,
         merged["due"], merged["status"], merged["note"],
         int(bool(merged["prepared"])), int(bool(merged["end_deadline"])),
         now(), item_id))
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
