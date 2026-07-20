"""The claim/evidence graph — now wired live, not a dead table."""

from __future__ import annotations

import pytest

from renv import claim, db, experiment, ingest, review


def _proj(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    return con


def test_add_and_list_claim(tmp_path):
    con = _proj(tmp_path)
    c = claim.add_claim(con, "p", "Span anchoring beats paper-level citation", kind="thesis")
    assert c["status"] == "open" and c["kind"] == "thesis"
    rows = claim.list_claims(con, "p")
    assert rows[0]["evidence_count"] == 0


def test_update_text_keeps_status(tmp_path):
    con = _proj(tmp_path)
    c = claim.add_claim(con, "p", "original wording", kind="assertion")
    got = claim.update_text(con, c["id"], "revised wording")
    assert got["text"] == "revised wording" and got["status"] == "open"
    with pytest.raises(ValueError):
        claim.update_text(con, c["id"], "   ")
    with pytest.raises(KeyError):
        claim.update_text(con, 999, "x")


def test_status_derives_from_evidence(tmp_path):
    con = _proj(tmp_path)
    ingest.add_paper(con, {"title": "ALCE", "authors": ["Gao"], "year": 2023}, key="gao2023_alce")

    class _Cit:
        source_id = "gao2023_alce"; claim = "x"; start, end = 1, 2
        quote = prefix = suffix = ""; support = "full"; support_score = 1.0
    cit = ingest.record_citation(con, "p", _Cit())

    c = claim.add_claim(con, "p", "NLI flags unsupported citations", kind="contribution")
    out = claim.link_evidence(con, c["id"], citation_id=cit["id"], stance="supports")
    assert out["status"] == "supported"


def test_refuting_evidence_marks_refuted(tmp_path):
    con = _proj(tmp_path)
    experiment.create_experiment(con, "p", "001")
    entry = tmp_path / "e.py"
    entry.write_text("import json,os\njson.dump({'r':0.1},open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "p", "001", entrypoint=str(entry), root=str(tmp_path))
    c = claim.add_claim(con, "p", "Method improves recall", kind="contribution")
    out = claim.link_evidence(con, c["id"], run_id=run["id"], stance="refutes",
                              note="recall dropped")
    assert out["status"] == "refuted"


def test_link_rejects_unfinished_run(tmp_path):
    con = _proj(tmp_path)
    experiment.create_experiment(con, "p", "001")
    con.execute("INSERT INTO run (experiment_id, status, started) "
                "VALUES ((SELECT id FROM experiment WHERE slug='001'), 'running', 'now')")
    con.commit()
    rid = con.execute("SELECT id FROM run").fetchone()["id"]
    c = claim.add_claim(con, "p", "x", kind="contribution")
    with pytest.raises(ValueError):
        claim.link_evidence(con, c["id"], run_id=rid)


def test_review_flags_unsupported_contribution(tmp_path):
    con = _proj(tmp_path)
    (tmp_path / "projects" / "p" / "text").mkdir(parents=True)
    (tmp_path / "projects" / "p" / "text" / "paper.tex").write_text(
        "\\begin{abstract}x\\end{abstract}\n\\bibliography{references}\n")
    claim.add_claim(con, "p", "Our key contribution", kind="contribution")  # no evidence
    findings = review.run_automated(con, str(tmp_path), "p")
    assert any(f["check_id"] == "claims-have-evidence" for f in findings)
