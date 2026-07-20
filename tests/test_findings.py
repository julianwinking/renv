"""Finding adjudication + dedup-by-memory: rejected findings are never re-raised."""

from __future__ import annotations

import json

import pytest

from renv import authoring, db, experiment, finding, review


def _project_with_paper(tmp_path, abstract):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    root = tmp_path / "projects" / "p"
    (root / "text").mkdir(parents=True)
    experiment.create_experiment(con, "p", "001", hypothesis="h")
    entry = tmp_path / "e.py"
    entry.write_text("import json,os\n"
                     "json.dump({'recall':0.80}, open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    experiment.run_experiment(con, "p", "001", entrypoint=str(entry), root=str(tmp_path))
    authoring.weave(con, "p", root)
    (root / "text" / "paper.tex").write_text(
        "\\begin{abstract}" + abstract + "\\end{abstract}\n\\input{results_table}\n"
        "\\bibliography{references}\n")
    return con, root


def test_migration_v2_present(tmp_path):
    con = db.connect(tmp_path)
    assert db.schema_version(con) >= 2
    names = {r["name"] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"finding", "adjudication", "finding_evidence", "review_run"} <= names


def test_review_persists_findings(tmp_path):
    con, _ = _project_with_paper(tmp_path, abstract="We reach recall 0.990.")  # fabricated
    res = review.review(con, str(tmp_path), "p")
    rows = finding.list_findings(con, "p")
    assert rows and any("0.990" in f["issue"] for f in rows)
    assert all(f["status"] == "open" for f in rows)


def test_reject_with_reasoning_suppresses_on_next_review(tmp_path):
    con, _ = _project_with_paper(tmp_path, abstract="We reach recall 0.990.")
    review.review(con, str(tmp_path), "p")
    fid = finding.list_findings(con, "p")[0]["id"]

    finding.adjudicate(con, fid, "reject", "0.99 is a rounded target stated in prose, intentional",
                       by="julian")
    # a second review must NOT re-raise the dismissed finding
    res2 = review.review(con, str(tmp_path), "p")
    assert all("0.990" not in f["issue"] for f in res2["open"])
    assert any("0.990" in f["issue"] for f in res2["suppressed"])
    assert res2["suppressed"][0]["prior_reason"].startswith("0.99")


def test_adjudication_requires_reasoning(tmp_path):
    con, _ = _project_with_paper(tmp_path, abstract="recall 0.990")
    review.review(con, str(tmp_path), "p")
    fid = finding.list_findings(con, "p")[0]["id"]
    with pytest.raises(ValueError):
        finding.adjudicate(con, fid, "reject", "   ")


def test_verdict_history_is_visible(tmp_path):
    con, _ = _project_with_paper(tmp_path, abstract="recall 0.990")
    review.review(con, str(tmp_path), "p")
    fid = finding.list_findings(con, "p")[0]["id"]
    finding.adjudicate(con, fid, "accept", "real issue, fix the abstract", by="agent")
    f = finding.get_finding(con, fid)
    assert f["status"] == "accepted"
    assert f["adjudications"][0]["reasoning"].startswith("real issue")
    assert f["adjudications"][0]["by"] == "agent"


def test_no_duplicate_open_finding_across_reviews(tmp_path):
    con, _ = _project_with_paper(tmp_path, abstract="recall 0.990")
    review.review(con, str(tmp_path), "p")
    review.review(con, str(tmp_path), "p")  # same condition, run twice
    matching = [f for f in finding.list_findings(con, "p") if "0.990" in f["issue"]]
    assert len(matching) == 1  # carried, not duplicated


def test_fixed_finding_auto_resolves(tmp_path):
    con, root = _project_with_paper(tmp_path, abstract="recall 0.990")
    review.review(con, str(tmp_path), "p")
    fid = finding.list_findings(con, "p")[0]["id"]
    # fix the paper so the condition no longer fires
    (root / "text" / "paper.tex").write_text(
        "\\begin{abstract}recall 0.800\\end{abstract}\n\\input{results_table}\n"
        "\\bibliography{references}\n")
    review.review(con, str(tmp_path), "p")
    assert finding.get_finding(con, fid)["status"] == "resolved"
