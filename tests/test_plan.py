"""Project planning — phases + milestones (v10), decoupled from the ledger."""

from __future__ import annotations

import pytest

from reref import db, plan


def _con(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    return con


def test_phase_and_milestone_lifecycle(tmp_path):
    con = _con(tmp_path)
    ph = plan.add_item(con, "p", "Dimension sweep", due="2026-07-25", start="2026-07-14")
    ms = plan.add_item(con, "p", "Abstract deadline", due="2026-08-01", kind="milestone")
    assert ph["kind"] == "phase" and ph["start"] == "2026-07-14"
    assert ms["kind"] == "milestone" and ms["start"] is None
    items = plan.list_items(con, "p")
    assert [i["id"] for i in items] == [ph["id"], ms["id"]]   # date-ordered
    done = plan.update_item(con, ph["id"], status="done")
    assert done["status"] == "done" and done["edited"]
    plan.delete_item(con, ms["id"])
    assert len(plan.list_items(con, "p")) == 1
    with pytest.raises(KeyError):
        plan.delete_item(con, ms["id"])


def test_validation(tmp_path):
    con = _con(tmp_path)
    with pytest.raises(ValueError):   # bad date format
        plan.add_item(con, "p", "x", due="soon")
    with pytest.raises(ValueError):   # start after due
        plan.add_item(con, "p", "x", due="2026-07-01", start="2026-07-09")
    with pytest.raises(ValueError):   # empty title
        plan.add_item(con, "p", "  ", due="2026-07-01")
    it = plan.add_item(con, "p", "ok", due="2026-07-01")
    with pytest.raises(ValueError):   # bogus status
        plan.update_item(con, it["id"], status="maybe")
    with pytest.raises(ValueError):   # immutable field
        plan.update_item(con, it["id"], kind="milestone")
