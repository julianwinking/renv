"""Graph regions — labeled frames, pure presentation state."""

from __future__ import annotations

import pytest

from reref import db, regions


def _proj(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    return con


def test_region_lifecycle(tmp_path):
    con = _proj(tmp_path)
    r = regions.add_region(con, "p", x=10, y=20, w=300, h=200, label="Phase 1", color="teal")
    assert r["label"] == "Phase 1" and r["color"] == "teal" and r["w"] == 300
    r = regions.update_region(con, r["id"], label="Phase 1: harness", color="amber", x=50, w=400)
    assert r["label"] == "Phase 1: harness" and r["color"] == "amber"
    assert r["x"] == 50 and r["w"] == 400 and r["y"] == 20   # unspecified fields kept
    assert len(regions.list_regions(con, "p")) == 1
    regions.delete_region(con, r["id"])
    assert regions.list_regions(con, "p") == []


def test_region_validation(tmp_path):
    con = _proj(tmp_path)
    with pytest.raises(ValueError):
        regions.add_region(con, "p", x=0, y=0, color="chartreuse")
    r = regions.add_region(con, "p", x=0, y=0)
    with pytest.raises(ValueError):
        regions.update_region(con, r["id"], color="chartreuse")
    with pytest.raises(KeyError):
        regions.delete_region(con, 999)
