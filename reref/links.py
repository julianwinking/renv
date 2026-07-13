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
    ("experiment", "experiment"): [
        ("parent", "Branches off (parent)", "parent"),
        ("relates_to", "Relates to", "context"),
    ],
    ("experiment", "claim"): [
        ("supports", "Supports (via latest run)", "evidence"),
        ("refutes", "Refutes (via latest run)", "evidence"),
        ("relates_to", "Relates to", "context"),
    ],
    # literature evidence: a verified citation supports/refutes a claim
    ("citation", "claim"): [
        ("supports", "Supports (literature)", "cite_evidence"),
        ("refutes", "Refutes (literature)", "cite_evidence"),
        ("relates_to", "Relates to", "context"),
    ],
    ("claim", "claim"): [
        ("depends_on", "Depends on", "relation"),
        ("contradicts", "Contradicts", "relation"),
        ("relates_to", "Relates to", "context"),
    ],
}
# Soft context links — each carries a SPECIFIC meaning, not a generic bag.
# The vocabulary (value → label); "relates_to" is the universal fallback and
# is appended to every listed pair automatically.
_CTX_LABEL = {
    "raises": "Raises",          # X surfaces a question
    "motivates": "Motivates",    # X is the reason to do Y
    "concerns": "Concerns",      # feedback is directed at X
    "informs": "Informs",        # a paper shapes X
    "about": "Is about",         # a question/note is about X
    "relates_to": "Relates to",  # generic
}

# The kinds that can carry soft links (everything conceptual; citations are
# evidence-only, code nodes are read-only @reref tags). Between ANY two of
# these, "Relates to" is always available — it genuinely applies to any pair,
# so nothing conceptual is ever un-connectable.
_CTX_KINDS = ("feedback", "note", "question", "hypothesis", "thought",
              "claim", "experiment", "paper", "finding")

# Specific verbs layered on top, only where they carry real meaning. Everything
# else falls back to relates_to alone.
_CTX_VERBS: dict[tuple[str, str], list[str]] = {
    # a result of research surfaces or motivates the next step
    ("claim", "question"): ["raises"],
    ("claim", "experiment"): ["motivates"],
    ("experiment", "question"): ["raises"],
    ("finding", "question"): ["raises"],
    ("observation", "question"): ["raises"],   # ('thought' node, see below)
    # open threads point at the work that will resolve them
    ("question", "experiment"): ["motivates"],
    ("question", "claim"): ["about"],
    ("question", "paper"): ["about"],
    ("hypothesis", "experiment"): ["motivates"],
    ("hypothesis", "claim"): ["motivates"],
    ("hypothesis", "question"): ["raises"],
    # external input is directed at something
    ("feedback", "claim"): ["concerns"],
    ("feedback", "experiment"): ["concerns"],
    ("feedback", "paper"): ["concerns"],
    ("feedback", "finding"): ["concerns"],
    ("feedback", "question"): ["raises"],
    # the literature shapes the work (evidence stays citation→claim, above)
    ("paper", "claim"): ["informs"],
    ("paper", "experiment"): ["informs"],
    ("paper", "question"): ["raises"],
}
# observation/decision/blocker log entries all render as the 'thought' node
_CTX_VERBS = {(("thought" if a == "observation" else a), b): v
              for (a, b), v in _CTX_VERBS.items()}

for _a in _CTX_KINDS:
    for _b in _CTX_KINDS:
        if (_a, _b) in CONNECTIONS:          # never shadow a strong pair
            continue
        verbs = _CTX_VERBS.get((_a, _b), [])
        CONNECTIONS[(_a, _b)] = [(v, _CTX_LABEL[v], "context") for v in verbs] \
            + [("relates_to", _CTX_LABEL["relates_to"], "context")]


def options_for(from_kind: str, to_kind: str) -> list[dict]:
    """The allowed relations for an ordered (from, to) pair — the central map."""
    return [{"value": v, "label": lbl, "mode": mode}
            for v, lbl, mode in CONNECTIONS.get((from_kind, to_kind), [])]


_KINDS = {"experiment", "claim", "citation", "paper", "finding", "note",
          "question", "hypothesis", "feedback", "thought", "code"}


def strong_pairs() -> list[tuple[str, str]]:
    """(from, to) pairs that carry a *typed* connection (parent/evidence/
    relation) — everything else is soft context. Useful for docs/audits."""
    return [pair for pair, rels in CONNECTIONS.items()
            if any(m != "context" for _, _, m in rels)]


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
