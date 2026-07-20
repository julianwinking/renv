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
    # tests = pre-registration (declared BEFORE running, no run required);
    # supports/refutes/inconclusive = evidence via the latest done run. The
    # declaration comes first in the list because it is the only edge that
    # cannot overclaim — evidence asserts a fact, a declaration only intent.
    ("experiment", "claim"): [
        ("tests", "Will test (pre-register)", "tests"),
        ("supports", "Supports (via latest run)", "evidence"),
        ("refutes", "Refutes (via latest run)", "evidence"),
        ("inconclusive", "Inconclusive (via latest run)", "evidence"),
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
    "suggests": "Suggests",      # an observation hints at a claim (proto-evidence)
    "based_on": "Based on",      # a decision rests on X
    "blocks": "Blocks",          # a blocker stops X
    "resolves": "Resolves",      # X clears a blocker
    "relates_to": "Relates to",  # generic
}

# The kinds that can carry soft links (everything conceptual; citations are
# evidence-only, code nodes are read-only @reref tags). Between ANY two of
# these, "Relates to" is always available — it genuinely applies to any pair,
# so nothing conceptual is ever un-connectable.
_CTX_KINDS = ("feedback", "note", "question", "hypothesis", "thought",
              "claim", "experiment", "paper", "finding", "pnote",
              "observation", "decision", "blocker")

# Specific verbs layered on top, only where they carry real meaning. Everything
# else falls back to relates_to alone.
_CTX_VERBS: dict[tuple[str, str], list[str]] = {
    # a result of research surfaces or motivates the next step
    ("claim", "question"): ["raises"],
    ("claim", "experiment"): ["motivates"],
    ("experiment", "question"): ["raises"],
    ("finding", "question"): ["raises"],
    # open threads point at the work that will resolve them
    ("question", "experiment"): ["motivates"],
    ("question", "claim"): ["about"],
    ("question", "paper"): ["about"],
    ("hypothesis", "experiment"): ["motivates"],
    ("hypothesis", "claim"): ["motivates"],
    ("hypothesis", "question"): ["raises"],
    ("note", "experiment"): ["motivates"],
    ("note", "question"): ["raises"],
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
    # a positional reading note carries a specific reading into the work: it
    # motivates an experiment, informs how a method is built, argues a claim
    ("pnote", "experiment"): ["motivates", "informs"],
    ("pnote", "claim"): ["motivates", "informs"],
    ("pnote", "hypothesis"): ["motivates"],
    ("pnote", "question"): ["raises"],
    ("pnote", "finding"): ["concerns"],
    # an observation is proto-evidence: it suggests a claim, raises a question,
    # motivates the experiment that will pin it down
    ("observation", "question"): ["raises"],
    ("observation", "claim"): ["suggests"],
    ("observation", "hypothesis"): ["suggests"],
    ("observation", "experiment"): ["motivates"],
    # a decision rests on inputs and points at the work it commits to; the
    # based_on trail is what makes "why did we do X" answerable a month later
    ("decision", "observation"): ["based_on"],
    ("decision", "claim"): ["based_on"],
    ("decision", "finding"): ["based_on"],
    ("decision", "feedback"): ["based_on"],
    ("decision", "paper"): ["based_on"],
    ("decision", "pnote"): ["based_on"],
    ("decision", "experiment"): ["motivates", "based_on"],
    ("decision", "blocker"): ["resolves"],
    # a blocker stops concrete work; work (or a decision) clears it
    ("blocker", "experiment"): ["blocks"],
    ("blocker", "claim"): ["blocks"],
    ("blocker", "question"): ["blocks"],
    ("blocker", "hypothesis"): ["blocks"],
    ("experiment", "blocker"): ["resolves"],
    ("feedback", "blocker"): ["resolves"],
}
# 'thought' renders the remaining log types (e.g. a result that answers a
# question) — give it the observation verbs, it plays the same role
for (_a, _b), _v in list(_CTX_VERBS.items()):
    if _a == "observation":
        _CTX_VERBS.setdefault(("thought", _b), _v)

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
          "question", "hypothesis", "feedback", "thought", "code", "pnote"}


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
    try:
        cur = con.execute(
            "INSERT INTO context_link (project_id, from_kind, from_id, to_kind, to_id, "
            "relation, note, created) VALUES (?,?,?,?,?,?,?,?)",
            (pid, from_kind, from_id, to_kind, to_id, relation, note, now()))
    except sqlite3.IntegrityError:
        raise ValueError(
            f"this {relation!r} link between {from_kind} #{from_id} and "
            f"{to_kind} #{to_id} already exists") from None
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


# Endpoints are polymorphic (kind + id), so SQLite FKs can't guard them.
# kind → the table that owns it; log-entry kinds all live in log_entry.
_LOG_KINDS = ("feedback", "question", "hypothesis", "thought",
              "observation", "decision", "blocker")


def graph_node_id(kind: str, id_: int) -> str:
    """The graph node id a context-link endpoint renders as — shared by the
    web graph and the lint layer so phase membership resolves consistently."""
    if kind == "experiment":
        return f"exp:{id_}"
    if kind in _LOG_KINDS:
        return f"log:{id_}"
    return f"{kind}:{id_}"



_KIND_TABLE = {"experiment": "experiment", "claim": "claim", "paper": "paper",
               "citation": "citation", "finding": "finding", "note": "note",
               "pnote": "paper_note",
               **{k: "log_entry" for k in _LOG_KINDS}}


def find_dangling(con: sqlite3.Connection, project: str) -> list[dict]:
    """Context links whose endpoint rows no longer exist (deleted pnotes,
    papers, …). The graph silently drops such edges — this makes them visible."""
    out = []
    for lk in list_links(con, project):
        for side in ("from", "to"):
            table = _KIND_TABLE.get(lk[f"{side}_kind"])
            if table is None:
                continue
            if not con.execute(f"SELECT 1 FROM {table} WHERE id=?",  # noqa: S608 — table from fixed map
                               (lk[f"{side}_id"],)).fetchone():
                out.append({**lk, "missing": f"{lk[f'{side}_kind']} #{lk[f'{side}_id']}"})
                break
    return out


def prune_dangling(con: sqlite3.Connection, project: str) -> int:
    """Delete dangling context links; returns how many were removed."""
    gone = find_dangling(con, project)
    for lk in gone:
        con.execute("DELETE FROM context_link WHERE id=?", (lk["id"],))
    con.commit()
    return len(gone)
