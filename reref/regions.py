"""Graph regions — labeled frames for grouping the canvas by phase or field.

Pure presentation. A region is a rectangle with a label and color; a node
"belongs" to it by sitting inside it (geometric, computed by the client), so
there is no membership table to maintain and the graph stays a view of the
store. Regions persist their position/size like node layout does.
"""

from __future__ import annotations

import sqlite3

from .db import now, project_id, row_to_dict

COLORS = ("slate", "teal", "violet", "amber", "rose", "blue")


def add_region(con: sqlite3.Connection, project: str, *, x: float, y: float,
               w: float = 360, h: float = 240, label: str = "",
               color: str = "slate") -> dict:
    if color not in COLORS:
        raise ValueError(f"color must be one of {COLORS}")
    pid = project_id(con, project)
    cur = con.execute(
        "INSERT INTO graph_region (project_id, label, color, x, y, w, h, created) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (pid, label, color, float(x), float(y), float(w), float(h), now()))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM graph_region WHERE id=?", (cur.lastrowid,)).fetchone())


def update_region(con: sqlite3.Connection, region_id: int, **fields) -> dict:
    row = con.execute("SELECT * FROM graph_region WHERE id=?", (region_id,)).fetchone()
    if not row:
        raise KeyError(f"no region #{region_id}")
    allowed = {"label", "color", "x", "y", "w", "h"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    if fields.get("color") and fields["color"] not in COLORS:
        raise ValueError(f"color must be one of {COLORS}")
    merged = {**row_to_dict(row), **fields}
    con.execute(
        "UPDATE graph_region SET label=?, color=?, x=?, y=?, w=?, h=? WHERE id=?",
        (merged["label"], merged["color"], float(merged["x"]), float(merged["y"]),
         float(merged["w"]), float(merged["h"]), region_id))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM graph_region WHERE id=?", (region_id,)).fetchone())


def list_regions(con: sqlite3.Connection, project: str) -> list[dict]:
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT * FROM graph_region WHERE project_id=? ORDER BY id", (pid,))]


def delete_region(con: sqlite3.Connection, region_id: int) -> None:
    if not con.execute("SELECT 1 FROM graph_region WHERE id=?", (region_id,)).fetchone():
        raise KeyError(f"no region #{region_id}")
    con.execute("DELETE FROM graph_region WHERE id=?", (region_id,))
    con.commit()


# approximate graph node box (matches cockpit layout.js SIZE)
_NODE_W, _NODE_H = 220, 96


def membership(con: sqlite3.Connection, project: str) -> dict[str, dict]:
    """node_id → the region that geometrically contains it (by its saved
    position's center). Only nodes with a saved graph_layout position can be
    in a region — a node is placed into a region by dragging it there."""
    from .db import project_id
    pid = project_id(con, project)
    regs = list_regions(con, project)
    if not regs:
        return {}
    out: dict[str, dict] = {}
    for r in con.execute(
            "SELECT node_id, x, y FROM graph_layout WHERE project_id=?", (pid,)):
        cx, cy = r["x"] + _NODE_W / 2, r["y"] + _NODE_H / 2
        for reg in regs:
            if reg["x"] <= cx <= reg["x"] + reg["w"] and reg["y"] <= cy <= reg["y"] + reg["h"]:
                out[r["node_id"]] = {"id": reg["id"], "label": reg["label"], "color": reg["color"]}
                break
    return out
