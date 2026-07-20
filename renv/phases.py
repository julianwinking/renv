"""Phase bands — plan phases projected onto the graph canvas as x-intervals.

ONE phase entity, three views: a `plan_item` of kind 'phase' is a Gantt row
(time), a full-height canvas band (space, this module), and the optional target
of a region link (v17). A band is the x-interval [x0, x1); a node belongs to
the band its saved center-x falls into — geometric membership, the same honest
philosophy as regions, but computed server-side so the lint layer can reason
about phase ORDER ("does this motivates-edge point backward?").

Left-to-right is the arrow of the project: ideation and reading on the left,
consolidation and experiment design in the middle, scaled experiments and
contributions on the right. Bands are presentation the store can *query*.
"""

from __future__ import annotations

import sqlite3

from .db import now, project_id, row_to_dict

# approximate graph node box (matches cockpit layout.js SIZE / regions.py)
_NODE_W = 220


def set_band(con: sqlite3.Connection, plan_item_id: int, x0: float, x1: float) -> dict:
    """Place (or move) a phase's band on the canvas. Only kind='phase' items
    can carry a band — milestones and deadlines are points in time, not spans."""
    p = con.execute("SELECT kind FROM plan_item WHERE id=?", (plan_item_id,)).fetchone()
    if not p:
        raise KeyError(f"no plan item #{plan_item_id}")
    if p["kind"] != "phase":
        raise ValueError("only a phase can have a canvas band")
    x0, x1 = float(x0), float(x1)
    if x1 - x0 < 80:
        raise ValueError("band must be at least 80 canvas units wide")
    con.execute(
        "INSERT INTO phase_band (plan_item_id, x0, x1, created) VALUES (?,?,?,?) "
        "ON CONFLICT(plan_item_id) DO UPDATE SET x0=excluded.x0, x1=excluded.x1",
        (plan_item_id, x0, x1, now()))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM phase_band WHERE plan_item_id=?", (plan_item_id,)).fetchone())


def set_color(con: sqlite3.Connection, plan_item_id: int, color: str) -> dict:
    """Set a band's explicit color ('' = auto by ordinal). Same palette as
    regions, so the canvas speaks one color language."""
    from .regions import COLORS
    if color not in COLORS and color != "":
        raise ValueError(f"color must be '' or one of {COLORS}")
    if not con.execute("SELECT 1 FROM phase_band WHERE plan_item_id=?",
                       (plan_item_id,)).fetchone():
        raise KeyError(f"plan item #{plan_item_id} has no band")
    con.execute("UPDATE phase_band SET color=? WHERE plan_item_id=?",
                (color, plan_item_id))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM phase_band WHERE plan_item_id=?", (plan_item_id,)).fetchone())


def clear_band(con: sqlite3.Connection, plan_item_id: int) -> None:
    if not con.execute("SELECT 1 FROM phase_band WHERE plan_item_id=?",
                       (plan_item_id,)).fetchone():
        raise KeyError(f"plan item #{plan_item_id} has no band")
    con.execute("DELETE FROM phase_band WHERE plan_item_id=?", (plan_item_id,))
    con.commit()


def list_phases(con: sqlite3.Connection, project: str) -> list[dict]:
    """All plan phases of a project with their band (x0/x1 NULL if unplaced),
    ordered left-to-right by band, then by date — the canvas order."""
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT p.id, p.title, p.start, p.due, p.status, b.x0, b.x1, b.color "
        "FROM plan_item p LEFT JOIN phase_band b ON b.plan_item_id=p.id "
        "WHERE p.project_id=? AND p.kind='phase' "
        "ORDER BY (b.x0 IS NULL), b.x0, COALESCE(p.start, p.due), p.due, p.id",
        (pid,)).fetchall()]


def ordinals(con: sqlite3.Connection, project: str) -> dict[int, int]:
    """plan_item_id → 0-based left-to-right position, for placed bands only."""
    placed = [p for p in list_phases(con, project) if p["x0"] is not None]
    return {p["id"]: i for i, p in enumerate(placed)}


def membership(con: sqlite3.Connection, project: str) -> dict[str, int]:
    """node_id → plan_item_id of the band containing the node's center-x.
    Only nodes with a saved position participate; overlapping bands resolve
    to the leftmost (x0 order), like regions resolve to the first hit."""
    pid = project_id(con, project)
    bands = [p for p in list_phases(con, project) if p["x0"] is not None]
    if not bands:
        return {}
    out: dict[str, int] = {}
    for r in con.execute(
            "SELECT node_id, x FROM graph_layout WHERE project_id=?", (pid,)):
        cx = r["x"] + _NODE_W / 2
        for b in bands:
            if b["x0"] <= cx < b["x1"]:
                out[r["node_id"]] = b["id"]
                break
    return out
