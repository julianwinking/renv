"""Context links — soft, annotative connections between graph entities.

The strong connections have dedicated homes: evidence (``claim_evidence``,
supports/refutes a claim), argument structure (``claim_relation``,
depends_on/contradicts), the experiment DAG (``experiment.parent_id``). This
module is for the *rest* — "this feedback relates to that claim", "this note
is about that experiment" — links that record a relationship without asserting
support. They never change any derived status.

The single source of truth for WHICH connections are allowed between which
kinds is ``CONNECTIONS`` below; the web/CLI/graph all consult it, so the rule
lives in one place.
"""

from __future__ import annotations

import sqlite3

from .db import now, project_id, row_to_dict

# What can connect to what. Keyed by (from_kind, to_kind) → list of relations.
# Each relation is (value, label, mode):
#   parent   — experiment DAG edge (experiment.set_parent)
#   evidence — claim_evidence via the source's latest done run (supports/refutes)
#   relation — claim_relation (depends_on/contradicts)
#   context  — a context_link row (this module) — soft, non-evidential
# Ordering matters: the first is the default when a pair has one obvious link.
CONNECTIONS: dict[tuple[str, str], list[tuple[str, str, str]]] = {
    ("experiment", "experiment"): [("parent", "Branches off (parent)", "parent")],
    ("experiment", "claim"): [
        ("supports", "Supports (via latest run)", "evidence"),
        ("refutes", "Refutes (via latest run)", "evidence"),
        ("relates_to", "Relates to", "context"),
    ],
    ("claim", "claim"): [
        ("depends_on", "Depends on", "relation"),
        ("contradicts", "Contradicts", "relation"),
        ("relates_to", "Relates to", "context"),
    ],
}
# Soft "relates to / about / motivates" from thinking-nodes onto research
# entities — generated for many (from, to) pairs so the map stays declarative.
# Kinds are the GRAPH node types (log entries other than question/hypothesis/
# feedback render as 'thought').
_THINKING = ("feedback", "note", "question", "hypothesis", "thought")
_TARGETS = ("claim", "experiment", "paper", "finding")
_CONTEXT_RELS = [("relates_to", "Relates to", "context"),
                 ("about", "Is about", "context"),
                 ("motivates", "Motivates", "context")]
for _f in _THINKING:
    for _t in _TARGETS:
        CONNECTIONS.setdefault((_f, _t), []).extend(_CONTEXT_RELS)


def options_for(from_kind: str, to_kind: str) -> list[dict]:
    """The allowed relations for an ordered (from, to) pair — the central map."""
    return [{"value": v, "label": lbl, "mode": mode}
            for v, lbl, mode in CONNECTIONS.get((from_kind, to_kind), [])]


_KINDS = {"experiment", "claim", "citation", "paper", "finding", "note",
          "question", "hypothesis", "feedback", "thought", "code"}


def add_link(con: sqlite3.Connection, project: str, *, from_kind: str, from_id: int,
             to_kind: str, to_id: int, relation: str, note: str | None = None) -> dict:
    """Record a context link. Validated against the CONNECTIONS map so the
    graph can only draw meaningful soft edges."""
    allowed = {o["value"] for o in options_for(from_kind, to_kind) if o["mode"] == "context"}
    if relation not in allowed:
        raise ValueError(
            f"{from_kind}→{to_kind} has no context relation {relation!r} "
            f"(allowed: {sorted(allowed) or 'none'})")
    pid = project_id(con, project)
    cur = con.execute(
        "INSERT INTO context_link (project_id, from_kind, from_id, to_kind, to_id, "
        "relation, note, created) VALUES (?,?,?,?,?,?,?,?)",
        (pid, from_kind, from_id, to_kind, to_id, relation, note, now()))
    con.commit()
    return row_to_dict(con.execute(
        "SELECT * FROM context_link WHERE id=?", (cur.lastrowid,)).fetchone())


def list_links(con: sqlite3.Connection, project: str) -> list[dict]:
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT * FROM context_link WHERE project_id=? ORDER BY id", (pid,))]


def delete_link(con: sqlite3.Connection, link_id: int) -> None:
    if not con.execute("SELECT 1 FROM context_link WHERE id=?", (link_id,)).fetchone():
        raise KeyError(f"no context link #{link_id}")
    con.execute("DELETE FROM context_link WHERE id=?", (link_id,))
    con.commit()
