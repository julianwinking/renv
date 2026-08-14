"""Finding adjudication: waivable rejects stay dismissed; provenance ones cannot."""

from __future__ import annotations

import argparse

import pytest

from renv.cli import cmd_review
from renv.research import authoring, db, experiment, finding, review


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


def _non_waivable_finding(check_id="cites-verify-full"):
    return {"check_id": check_id, "section": "all",
            "dimension": "correctness", "severity": "high",
            "issue": f"{check_id} violation",
            "location": {"quote": check_id}}


@pytest.mark.parametrize("check_id", sorted(finding.NON_WAIVABLE))
def test_reject_non_waivable_is_refused(tmp_path, check_id):
    con, _ = _project_with_paper(tmp_path, abstract="recall 0.800")
    fid = finding.persist_findings(con, "p", [_non_waivable_finding(check_id)])["open"][0]["id"]
    with pytest.raises(ValueError, match="non-waivable"):
        finding.adjudicate(con, fid, "reject", "I don't want to fix this")
    assert finding.get_finding(con, fid)["status"] == "open"


@pytest.mark.parametrize("check_id", sorted(finding.NON_WAIVABLE))
def test_non_waivable_rejected_finding_is_reopened(tmp_path, check_id):
    con, _ = _project_with_paper(tmp_path, abstract="recall 0.800")
    payload = _non_waivable_finding(check_id)
    fid = finding.persist_findings(con, "p", [payload])["open"][0]["id"]
    con.execute("UPDATE finding SET status='rejected' WHERE id=?", (fid,))
    con.execute(
        "INSERT INTO adjudication (finding_id, verdict, reasoning, by, ts) "
        "VALUES (?,?,?,?,?)", (fid, "reject", "historical dismiss", "test", "t"))
    con.commit()
    res = finding.persist_findings(con, "p", [payload])
    assert res["open"][0]["id"] == fid
    assert finding.get_finding(con, fid)["status"] == "open"
    fp = finding.fingerprint(payload)
    n = con.execute(
        "SELECT COUNT(*) n FROM finding WHERE fingerprint=?", (fp,)).fetchone()["n"]
    assert n == 1


def test_review_does_not_resolve_lint_findings(tmp_path):
    from renv.research import claim, lint
    con, root = _project_with_paper(tmp_path, abstract="recall 0.800")
    claim.add_claim(con, "p", "our grand thesis", kind="thesis")
    out = lint.run(con, "p")
    hits = [f for f in out["open"] if f["rule"] == "headline-unbacked"]
    assert hits
    fid = hits[0]["id"]
    review.review(con, str(tmp_path), "p")
    assert finding.get_finding(con, fid)["status"] == "open"


def test_cmd_review_strict_exits_on_lint_high(tmp_path):
    con, _ = _project_with_paper(tmp_path, abstract="recall 0.800")
    pid = db.project_id(con, "p")
    con.execute("INSERT INTO log_entry (project_id, type, ts, body_md) "
                "VALUES (?, 'result', 'now', 'made-up number')", (pid,))
    con.commit()
    cmd_review(argparse.Namespace(corpus=str(tmp_path), project="p", strict=False))
    with pytest.raises(SystemExit) as ei:
        cmd_review(argparse.Namespace(corpus=str(tmp_path), project="p", strict=True))
    assert ei.value.code == 1
