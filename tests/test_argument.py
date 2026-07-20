"""Argument analysis: foundation propagation, contradictions, frontier."""

from __future__ import annotations

from renv import argument, claim, db, experiment


def _proj(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    return con


def _support(con, claim_id, tmp_path, slug):
    """Attach a real supporting run to a claim so its status derives to supported."""
    experiment.create_experiment(con, "p", slug)
    e = tmp_path / f"{slug}.py"
    e.write_text("import json,os\njson.dump({'m':1.0},"
                 "open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "p", slug, entrypoint=str(e), root=str(tmp_path))
    claim.link_evidence(con, claim_id, run_id=run["id"], stance="supports")


def _refute(con, claim_id, tmp_path, slug):
    experiment.create_experiment(con, "p", slug)
    e = tmp_path / f"{slug}.py"
    e.write_text("import json,os\njson.dump({'m':1.0},"
                 "open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    run = experiment.run_experiment(con, "p", slug, entrypoint=str(e), root=str(tmp_path))
    claim.link_evidence(con, claim_id, run_id=run["id"], stance="refutes")


def test_foundation_propagates(tmp_path):
    con = _proj(tmp_path)
    thesis = claim.add_claim(con, "p", "thesis", kind="thesis")
    lemma_a = claim.add_claim(con, "p", "lemma A")
    lemma_b = claim.add_claim(con, "p", "lemma B")
    claim.relate(con, thesis["id"], lemma_a["id"], kind="depends_on")
    claim.relate(con, thesis["id"], lemma_b["id"], kind="depends_on")

    # both lemmas open → thesis foundation weak (no lemma refuted yet)
    a = argument.analyze(con, "p")
    tc = next(c for c in a["claims"] if c["id"] == thesis["id"])
    assert tc["foundation"] == "weak"

    # support A, refute B → foundation broken; the thesis itself is still 'open'
    _support(con, lemma_a["id"], tmp_path, "sa")
    _refute(con, lemma_b["id"], tmp_path, "sb")
    a = argument.analyze(con, "p")
    tc = next(c for c in a["claims"] if c["id"] == thesis["id"])
    assert tc["foundation"] == "broken"
    assert lemma_b["id"] in tc["foundation_issues"]
    assert a["summary"]["broken_foundations"] == 1
    # local status is untouched by structural analysis
    assert claim.get_claim(con, thesis["id"])["status"] == "open"


def test_contradiction_surfaces_only_between_supported(tmp_path):
    con = _proj(tmp_path)
    a1 = claim.add_claim(con, "p", "A", kind="contribution")
    a2 = claim.add_claim(con, "p", "not A", kind="contribution")
    claim.relate(con, a1["id"], a2["id"], kind="contradicts")
    # neither supported yet → no crisis
    assert argument.analyze(con, "p")["contradictions"] == []
    _support(con, a1["id"], tmp_path, "s1")
    _support(con, a2["id"], tmp_path, "s2")
    crises = argument.analyze(con, "p")["contradictions"]
    assert len(crises) == 1 and {crises[0]["a"], crises[0]["b"]} == {a1["id"], a2["id"]}


def test_frontier_ranks_by_criticality(tmp_path):
    con = _proj(tmp_path)
    thesis = claim.add_claim(con, "p", "the thesis", kind="thesis")
    lemma = claim.add_claim(con, "p", "a lemma the thesis needs")
    contrib = claim.add_claim(con, "p", "a standalone contribution", kind="contribution")
    assertion = claim.add_claim(con, "p", "a minor assertion", kind="assertion")
    claim.relate(con, thesis["id"], lemma["id"], kind="depends_on")

    fr = argument.analyze(con, "p")["frontier"]
    ids = [f["id"] for f in fr]
    assert thesis["id"] in ids and lemma["id"] in ids and contrib["id"] in ids
    assert assertion["id"] not in ids           # not critical, not thesis/contribution
    assert ids[0] == thesis["id"]               # thesis ranks first
    assert ids.index(lemma["id"]) < ids.index(contrib["id"])  # thesis-critical lemma beats standalone
    assert all("No evidence yet" in f["next"] for f in fr if f["evidence_count"] == 0)
