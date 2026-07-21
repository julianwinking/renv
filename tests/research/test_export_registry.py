"""Every table the store knows is either exported or a declared presentation
exclusion — the committed JSONL snapshot must never silently lose a concept
(this bug happened: claim relations and paper notes were missing for weeks)."""

from __future__ import annotations

from renv.papers import ingest
from renv.research import claim, db


def _all_tables(con):
    return {r["name"] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite%'").fetchall()}


def test_every_table_exported_or_declared_presentation(tmp_path):
    con = db.connect(tmp_path)
    assert _all_tables(con) == set(db.TABLES) | db.PRESENTATION_TABLES
    assert not set(db.TABLES) & db.PRESENTATION_TABLES


def test_roundtrip_preserves_relations_and_globals(tmp_path):
    src = tmp_path / "a"; dst = tmp_path / "b"
    con = db.connect(src)
    db.ensure_project(con, "p")
    a = claim.add_claim(con, "p", "first")
    b = claim.add_claim(con, "p", "second")
    claim.relate(con, b["id"], a["id"], kind="depends_on")
    ingest.add_paper(con, {"title": "T", "authors": ["X"], "year": 2026}, key="x2026_t")
    out = db.export(con, src)
    con2 = db.connect(dst)
    db.import_jsonl(con2, dst, source=out)
    again = claim.get_claim(con2, b["id"])
    assert [r["related_id"] for r in again["relations"]] == [a["id"]]
    assert con2.execute("SELECT COUNT(*) c FROM paper WHERE key='x2026_t'").fetchone()["c"] == 1


def test_future_database_is_refused(tmp_path):
    import pytest
    con = db.connect(tmp_path)
    con.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 5}")
    con.commit(); con.close()
    with pytest.raises(RuntimeError, match="newer renv"):
        db.connect(tmp_path)


def test_future_export_is_refused_and_manifest_deterministic(tmp_path):
    import json as _j

    import pytest
    con = db.connect(tmp_path / "a")
    out = db.export(con, tmp_path / "a")
    m = _j.loads((out / "manifest.json").read_text())
    assert m == {"schema_version": len(db.MIGRATIONS)}   # no timestamps: git-diffable
    (out / "manifest.json").write_text('{"schema_version": 999}')
    con2 = db.connect(tmp_path / "b")
    with pytest.raises(RuntimeError, match="update renv"):
        db.import_jsonl(con2, tmp_path / "b", source=out)
