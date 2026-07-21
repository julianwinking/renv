"""Context links + the central connection registry."""

from __future__ import annotations

import pytest

from renv.research import claim, db, links


def _proj(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    return con


def test_registry_options():
    # the map is the single source of truth for what can connect
    assert any(o["mode"] == "parent" for o in links.options_for("experiment", "experiment"))
    ev = links.options_for("experiment", "claim")
    assert {o["value"] for o in ev} >= {"supports", "refutes", "relates_to"}
    # literature evidence: citation → claim
    assert {o["value"] for o in links.options_for("citation", "claim")} >= {"supports", "refutes"}
    # curated verbs where meaningful, on top of universal relates_to
    assert {o["value"] for o in links.options_for("claim", "question")} == {"raises", "relates_to"}
    assert {o["value"] for o in links.options_for("feedback", "claim")} == {"concerns", "relates_to"}
    assert {o["value"] for o in links.options_for("paper", "claim")} == {"informs", "relates_to"}
    # any two conceptual nodes always at least "relate to" each other
    assert {o["value"] for o in links.options_for("note", "thought")} == {"relates_to"}
    assert {o["value"] for o in links.options_for("thought", "question")} == {"raises", "relates_to"}
    assert {o["value"] for o in links.options_for("paper", "note")} == {"relates_to"}
    # citations are evidence-only, not soft-linkable
    assert links.options_for("citation", "note") == []


def test_add_and_list_context_link(tmp_path):
    con = _proj(tmp_path)
    c = claim.add_claim(con, "p", "targeted beats random", kind="thesis")
    lk = links.add_link(con, "p", from_kind="feedback", from_id=10,
                        to_kind="claim", to_id=c["id"], relation="relates_to",
                        note="advisor flagged this")
    assert lk["relation"] == "relates_to"
    rows = links.list_links(con, "p")
    assert len(rows) == 1 and rows[0]["to_id"] == c["id"]
    # status is untouched — context links are never evidence
    assert claim.get_claim(con, c["id"])["status"] == "open"
    links.delete_link(con, lk["id"])
    assert links.list_links(con, "p") == []


def test_rejects_meaningless_relation(tmp_path):
    con = _proj(tmp_path)
    with pytest.raises(ValueError):   # supports is evidence, not a context relation
        links.add_link(con, "p", from_kind="feedback", from_id=1,
                       to_kind="claim", to_id=1, relation="supports")
    with pytest.raises(ValueError):   # citation→note has no context relation at all
        links.add_link(con, "p", from_kind="citation", from_id=1,
                       to_kind="note", to_id=1, relation="relates_to")
    with pytest.raises(ValueError):   # feedback→claim allows concerns, not "raises"
        links.add_link(con, "p", from_kind="feedback", from_id=1,
                       to_kind="claim", to_id=1, relation="raises")
