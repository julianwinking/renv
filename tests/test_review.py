"""Phase E: automated per-section critique (Pillar 8)."""

from __future__ import annotations

import json
from pathlib import Path

from renv import authoring, db, experiment, review


def _project_with_run(tmp_path, recall=0.80):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    root = tmp_path / "projects" / "p"
    (root / "text").mkdir(parents=True)
    experiment.create_experiment(con, "p", "001", hypothesis="dense helps")
    entry = tmp_path / "e.py"
    entry.write_text("import json,os\n"
                     f"json.dump({{'recall':{recall}}}, open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    experiment.run_experiment(con, "p", "001", entrypoint=str(entry), root=str(tmp_path))
    authoring.weave(con, "p", root)
    return con, root


def _write_paper(root, abstract="", body=""):
    (root / "text" / "paper.tex").write_text(
        "\\begin{abstract}" + abstract + "\\end{abstract}\n"
        "\\input{results_table}\n" + body + "\n\\bibliography{references}\n")


def test_clean_paper_has_no_high_findings(tmp_path):
    con, root = _project_with_run(tmp_path, recall=0.80)
    _write_paper(root, abstract="We reach recall of 0.800 on the benchmark.")
    findings = review.run_automated(con, str(tmp_path), "p")
    highs = [f for f in findings if f["severity"] == "high"]
    assert not highs, highs


def test_fabricated_abstract_number_is_flagged(tmp_path):
    con, root = _project_with_run(tmp_path, recall=0.80)
    _write_paper(root, abstract="We improve recall to 0.990, a huge gain.")
    findings = review.run_automated(con, str(tmp_path), "p")
    ids = {f["check_id"] for f in findings}
    assert "abs-claims-match-metrics" in ids
    assert any("0.990" in f["issue"] for f in findings)


def test_unverified_spancite_is_flagged(tmp_path):
    con, root = _project_with_run(tmp_path)
    # a citation row where the cite only partially supports the claim
    class _Cit:
        source_id = "gao2023_alce"; claim = "q"; start, end = 100, 200
        quote = prefix = suffix = ""; support = "partial"; support_score = 0.5
    from renv import ingest
    ingest.record_citation(con, "p", _Cit())
    _write_paper(root, body="A claim.\\spancite{gao2023_alce}{100}{200}{q}")
    findings = review.run_automated(con, str(tmp_path), "p")
    assert any(f["check_id"] == "cites-verify-full" and "partial" in f["issue"]
               for f in findings)


def test_missing_bib_entry_is_flagged(tmp_path):
    con, root = _project_with_run(tmp_path)
    (root / "text" / "references.bib").write_text("")  # empty bib
    _write_paper(root, body="See \\cite{smith2024}.")
    findings = review.run_automated(con, str(tmp_path), "p")
    assert any(f["check_id"] == "bib-coverage" and "smith2024" in f["issue"]
               for f in findings)


def test_review_writes_report(tmp_path):
    con, root = _project_with_run(tmp_path)
    _write_paper(root, abstract="recall 0.800")
    res = review.review(con, str(tmp_path), "p")
    assert Path(res["report"]).exists()
    assert "# Review — p" in Path(res["report"]).read_text()
