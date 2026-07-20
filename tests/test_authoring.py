"""Phase C: ideation + manuscript scaffolding and assembly (weave)."""

from __future__ import annotations

import json
from pathlib import Path

from reref import authoring, db, experiment


def _project(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="A Paper")
    return con, tmp_path / "projects" / "p"


def test_seed_ideation_is_store_native_and_idempotent(tmp_path):
    con, _ = _project(tmp_path)
    seeded = authoring.seed_ideation(con, "p")
    assert seeded and seeded["type"] == "question" and "thesis" in seeded["body_md"]
    # idempotent: a project with any log history is never re-seeded
    assert authoring.seed_ideation(con, "p") is None


def test_scaffold_paper_writes_preamble_and_template(tmp_path):
    _, root = _project(tmp_path)
    written = authoring.scaffold_paper(root, "p", "A Paper")
    names = {p.name for p in written}
    assert {"preamble.tex", "paper.tex"} <= names
    paper = (root / "text" / "paper.tex").read_text()
    assert "A Paper" in paper and r"\bibliography{references}" in paper
    assert r"\newcommand{\spancite}" in (root / "text" / "preamble.tex").read_text()


def _run_with_metrics(con, tmp_path, slug, recall):
    experiment.create_experiment(con, "p", slug)
    entry = tmp_path / f"{slug}.py"
    entry.write_text(
        "import json,os\n"
        f"json.dump({{'recall':{recall},'precision':0.9}}, "
        "open(os.environ['REREF_RUN_DIR']+'/metrics.json','w'))\n")
    experiment.run_experiment(con, "p", slug, entrypoint=str(entry), root=str(tmp_path))


def test_weave_results_table_from_metrics(tmp_path):
    con, root = _project(tmp_path)
    _run_with_metrics(con, tmp_path, "001-base", 0.80)
    _run_with_metrics(con, tmp_path, "002-dense", 0.86)

    out = authoring.weave_results_table(con, "p", root)
    tex = out.read_text()
    assert "GENERATED" in tex
    assert "recall" in tex and "precision" in tex
    assert "0.800" in tex and "0.860" in tex          # numbers come from metric rows
    assert "001-base" in tex and "002-dense" in tex
    assert r"\toprule" in tex and r"\bottomrule" in tex


def test_weave_results_table_handles_no_metrics(tmp_path):
    con, root = _project(tmp_path)
    experiment.create_experiment(con, "p", "001-base")  # no run yet
    tex = authoring.weave_results_table(con, "p", root).read_text()
    assert "No metrics yet" in tex


def test_weave_bib_stubs_from_citation_table(tmp_path):
    con, root = _project(tmp_path)

    class _Cit:
        def __init__(self, sid):
            self.source_id = sid; self.claim = "c"; self.start = 1; self.end = 2
            self.quote = self.prefix = self.suffix = ""; self.support = "full"; self.support_score = 1.0
    from reref import ingest
    ingest.record_citation(con, "p", _Cit("gao2023_alce"))
    ingest.record_citation(con, "p", _Cit("chen2025_telephone"))
    bib = authoring.weave_bib(con, "p", root).read_text()
    assert "@misc{gao2023_alce" in bib and "@misc{chen2025_telephone" in bib


def test_weave_bib_prefers_paper_table(tmp_path):
    con, root = _project(tmp_path)
    con.execute(
        "INSERT INTO paper (key, title, authors_json, year, doi, added) "
        "VALUES ('gao2023_alce', 'ALCE', ?, 2023, '10.x/y', 'now')",
        (json.dumps(["Tianyu Gao", "Howard Yen"]),))
    con.commit()
    bib = authoring.weave_bib(con, "p", root).read_text()
    assert "@article{gao2023_alce" in bib
    assert "Tianyu Gao and Howard Yen" in bib and "2023" in bib
