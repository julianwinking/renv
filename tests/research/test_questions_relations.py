"""Round 4: question/feedback log entries, claim relations, DAG re-parenting."""

from __future__ import annotations

import pytest

from renv.research import claim, db, experiment, log


def test_question_answer_lifecycle(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    q = log.add_entry(con, "p", "question", "Does the gap grow with d?")
    # open until answered — status derived, not stored
    entries = {e["id"]: e for e in log.list_entries(con, "p")}
    assert entries[q["id"]]["answered_by"] is None
    a = log.add_entry(con, "p", "observation", "Yes: gap ~ eps*(1-1/sqrt(d)).",
                      answers=q["id"])
    entries = {e["id"]: e for e in log.list_entries(con, "p")}
    assert entries[q["id"]]["answered_by"] == a["id"]
    assert entries[a["id"]]["answers"] == q["id"]


def test_answer_validation(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    db.ensure_project(con, "other", title="O")
    d = log.add_entry(con, "p", "decision", "not a question")
    q_other = log.add_entry(con, "other", "question", "foreign question")
    with pytest.raises(ValueError):   # target must be a question
        log.add_entry(con, "p", "observation", "x", answers=d["id"])
    with pytest.raises(ValueError):   # target must be same project
        log.add_entry(con, "p", "observation", "x", answers=q_other["id"])
    with pytest.raises(ValueError):   # target must exist
        log.add_entry(con, "p", "observation", "x", answers=999)


def test_edit_entry_stamps_edited(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    e = log.add_entry(con, "p", "decision", "original")
    assert e["edited"] is None
    got = log.update_entry(con, e["id"], "revised")
    assert got["body_md"] == "revised" and got["edited"] and got["ts"] == e["ts"]
    n = log.add_note(con, "p", "note body", title="T")
    got = log.update_note(con, n["id"], "new body")
    assert got["body_md"] == "new body" and got["edited"] and got["title"] == "T"
    with pytest.raises(KeyError):
        log.update_entry(con, 999, "x")


def test_feedback_with_source(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    e = log.add_entry(con, "p", "feedback", "Compare against an FGSM baseline.",
                      source="advisor: Prof. X")
    got = log.list_entries(con, "p")[0]
    assert got["type"] == "feedback" and got["source"] == "advisor: Prof. X"
    assert e["id"] == got["id"]


def test_claim_relations_and_cycle_guard(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    thesis = claim.add_claim(con, "p", "Targeted beats random", kind="thesis")
    lemma = claim.add_claim(con, "p", "Random shift is eps/sqrt(d)")
    claim.relate(con, thesis["id"], lemma["id"], kind="depends_on",
                 note="gap size is derived from the lemma")
    full = claim.get_claim(con, thesis["id"])
    assert full["relations"][0]["related_id"] == lemma["id"]
    assert full["relations"][0]["note"] == "gap size is derived from the lemma"
    # relations are structure, not proof — status stays derived from evidence
    assert full["status"] == "open"
    with pytest.raises(ValueError):   # cycle refused
        claim.relate(con, lemma["id"], thesis["id"], kind="depends_on")
    with pytest.raises(ValueError):   # self-relation refused
        claim.relate(con, thesis["id"], thesis["id"])
    assert claim.list_relations(con, "p")[0]["kind"] == "depends_on"


def test_set_parent_reparents_and_refuses_cycles(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    experiment.create_experiment(con, "p", "001")
    experiment.create_experiment(con, "p", "002", parent="001")
    experiment.create_experiment(con, "p", "003")
    got = experiment.set_parent(con, "p", "003", "002")
    assert got["parent_id"] is not None
    with pytest.raises(ValueError):   # 001 → descendant would cycle
        experiment.set_parent(con, "p", "001", "003")
    assert experiment.set_parent(con, "p", "003", None)["parent_id"] is None


def test_migration_from_v5_preserves_log(tmp_path):
    # build a DB frozen at v5 with a log row, then reopen at head — the
    # log_entry rebuild must carry rows over and leave no dangling FKs
    orig = db.MIGRATIONS
    db.MIGRATIONS = orig[:5]
    try:
        con = db.connect(tmp_path)
        db.ensure_project(con, "p", title="P")
        con.execute(   # v5-era write: no answers/source columns yet
            "INSERT INTO log_entry (project_id, type, ts, body_md) "
            "VALUES ((SELECT id FROM project WHERE slug='p'), 'decision', "
            "'2026-07-13T00:00:00+00:00', 'pre-migration entry')")
        con.commit()
        con.close()
    finally:
        db.MIGRATIONS = orig
    con = db.connect(tmp_path)   # migrates v6+v7
    assert db.schema_version(con) == len(db.MIGRATIONS)
    entries = log.list_entries(con, "p")
    assert entries[0]["body_md"] == "pre-migration entry"
    log.add_entry(con, "p", "question", "post-migration question works?")
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
