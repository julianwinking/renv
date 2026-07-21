"""The evidence lifecycle, pre-registration, connection fixes, phases, and lints."""

from __future__ import annotations

import pytest

from renv.papers import ingest
from renv.research import claim, db, experiment, links, lint, log, phases


def _proj(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    return con


def _run(con, tmp_path, slug="001"):
    experiment.create_experiment(con, "p", slug)
    entry = tmp_path / f"e_{slug}.py"
    entry.write_text(
        "import json,os\n"
        "json.dump({'r':0.5},open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    return experiment.run_experiment(con, "p", slug, entrypoint=str(entry), root=str(tmp_path))


def _cite(con, support="full"):
    ingest.add_paper(con, {"title": "T", "authors": ["A"], "year": 2024}, key="t2024")

    class _Cit:
        source_id = "t2024"; claim = "x"; start, end = 1, 2
        quote = prefix = suffix = ""
        support_score = 1.0
    _Cit.support = support
    return ingest.record_citation(con, "p", _Cit())


# --- pre-registration (experiment tests claim) --------------------------------
def test_declared_test_marks_evidence_preregistered(tmp_path):
    con = _proj(tmp_path)
    run = _run(con, tmp_path)
    h = claim.add_claim(con, "p", "eps scales with sqrt(d)", kind="hypothesis")
    claim.declare_test(con, "p", "001", h["id"])
    out = claim.link_evidence(con, h["id"], run_id=run["id"], stance="supports")
    assert out["evidence"][0]["preregistered"] == 1
    assert out["tests"][0]["experiment_slug"] == "001"


def test_undeclared_evidence_is_exploratory(tmp_path):
    con = _proj(tmp_path)
    run = _run(con, tmp_path)
    c = claim.add_claim(con, "p", "some other claim", kind="contribution")
    out = claim.link_evidence(con, c["id"], run_id=run["id"], stance="supports")
    assert out["evidence"][0]["preregistered"] == 0


def test_declare_test_rejects_cross_project_and_unknown(tmp_path):
    con = _proj(tmp_path)
    experiment.create_experiment(con, "p", "001")
    with pytest.raises(KeyError):
        claim.declare_test(con, "p", "001", 999)
    with pytest.raises(KeyError):
        claim.declare_test(con, "p", "nope", 1)


# --- evidence lifecycle --------------------------------------------------------
def test_verdict_none_citation_cannot_support(tmp_path):
    con = _proj(tmp_path)
    cit = _cite(con, support="none")
    c = claim.add_claim(con, "p", "the literature backs this", kind="assertion")
    with pytest.raises(ValueError, match="verifier verdict"):
        claim.link_evidence(con, c["id"], citation_id=cit["id"], stance="supports")


def test_inconclusive_records_but_moves_nothing(tmp_path):
    con = _proj(tmp_path)
    run = _run(con, tmp_path)
    c = claim.add_claim(con, "p", "unclear effect", kind="assertion")
    out = claim.link_evidence(con, c["id"], run_id=run["id"], stance="inconclusive")
    assert out["status"] == "open" and out["evidence"][0]["stance"] == "inconclusive"


def test_retraction_recomputes_status_and_keeps_history(tmp_path):
    con = _proj(tmp_path)
    run = _run(con, tmp_path)
    c = claim.add_claim(con, "p", "method helps", kind="contribution")
    out = claim.link_evidence(con, c["id"], run_id=run["id"], stance="refutes")
    assert out["status"] == "refuted"
    ev_id = out["evidence"][0]["id"]
    with pytest.raises(ValueError):
        claim.retract_evidence(con, ev_id, "   ")          # reason required
    out = claim.retract_evidence(con, ev_id, "bug in the eval harness")
    assert out["status"] == "open"                          # veto lifted
    assert out["evidence"][0]["retracted"]                  # history kept
    with pytest.raises(ValueError):
        claim.retract_evidence(con, ev_id, "twice")         # already retracted
    assert claim.list_claims(con, "p")[0]["evidence_count"] == 0


def test_claim_edit_marks_evidence_stale_and_confirm_clears(tmp_path):
    con = _proj(tmp_path)
    cit = _cite(con)
    c = claim.add_claim(con, "p", "improves accuracy by 5%", kind="assertion")
    out = claim.link_evidence(con, c["id"], citation_id=cit["id"], stance="supports")
    ev_id = out["evidence"][0]["id"]
    claim.update_text(con, c["id"], "improves accuracy by 5%")   # unchanged → not stale
    assert claim.get_claim(con, c["id"])["evidence"][0]["stale"] == 0
    claim.update_text(con, c["id"], "improves accuracy by 15%")
    assert claim.get_claim(con, c["id"])["evidence"][0]["stale"] == 1
    claim.confirm_evidence(con, ev_id)
    assert claim.get_claim(con, c["id"])["evidence"][0]["stale"] == 0


def test_grade_validated(tmp_path):
    con = _proj(tmp_path)
    run = _run(con, tmp_path)
    c = claim.add_claim(con, "p", "x", kind="assertion")
    with pytest.raises(ValueError):
        claim.link_evidence(con, c["id"], run_id=run["id"], grade="rock-solid")


def test_delete_relation(tmp_path):
    con = _proj(tmp_path)
    a = claim.add_claim(con, "p", "a")
    b = claim.add_claim(con, "p", "b")
    out = claim.relate(con, a["id"], b["id"], kind="depends_on")
    rid = out["relations"][0]["id"]
    claim.delete_relation(con, rid)
    assert claim.get_claim(con, a["id"])["relations"] == []
    with pytest.raises(KeyError):
        claim.delete_relation(con, rid)


# --- connection registry: no quarantined kinds --------------------------------
def test_observation_decision_blocker_are_connectable(tmp_path):
    con = _proj(tmp_path)
    o = log.add_entry(con, "p", "observation", "gap grows with d")
    q = log.add_entry(con, "p", "question", "why sqrt(d)?")
    d_ = log.add_entry(con, "p", "decision", "use closed-form first")
    bl = log.add_entry(con, "p", "blocker", "cluster down")
    experiment.create_experiment(con, "p", "001")
    exp_id = con.execute("SELECT id FROM experiment WHERE slug='001'").fetchone()["id"]

    assert {o["value"] for o in links.options_for("observation", "question")} >= {"raises", "relates_to"}
    links.add_link(con, "p", from_kind="observation", from_id=o["id"],
                   to_kind="question", to_id=q["id"], relation="raises")
    links.add_link(con, "p", from_kind="decision", from_id=d_["id"],
                   to_kind="observation", to_id=o["id"], relation="based_on")
    links.add_link(con, "p", from_kind="blocker", from_id=bl["id"],
                   to_kind="experiment", to_id=exp_id, relation="blocks")
    assert len(links.list_links(con, "p")) == 3


def test_duplicate_link_refused(tmp_path):
    con = _proj(tmp_path)
    q = log.add_entry(con, "p", "question", "q")
    experiment.create_experiment(con, "p", "001")
    exp_id = con.execute("SELECT id FROM experiment WHERE slug='001'").fetchone()["id"]
    links.add_link(con, "p", from_kind="question", from_id=q["id"],
                   to_kind="experiment", to_id=exp_id, relation="motivates")
    with pytest.raises(ValueError, match="already exists"):
        links.add_link(con, "p", from_kind="question", from_id=q["id"],
                       to_kind="experiment", to_id=exp_id, relation="motivates")


def test_prune_dangling_links(tmp_path):
    con = _proj(tmp_path)
    q = log.add_entry(con, "p", "question", "q")
    c = claim.add_claim(con, "p", "c")
    links.add_link(con, "p", from_kind="question", from_id=q["id"],
                   to_kind="claim", to_id=c["id"], relation="about")
    con.execute("DELETE FROM claim WHERE id=?", (c["id"],))
    con.commit()
    assert len(links.find_dangling(con, "p")) == 1
    assert links.prune_dangling(con, "p") == 1
    assert links.list_links(con, "p") == []


def test_experiment_claim_offers_tests_first(tmp_path):
    opts = links.options_for("experiment", "claim")
    assert opts[0]["value"] == "tests" and opts[0]["mode"] == "tests"
    assert {o["value"] for o in opts} >= {"supports", "refutes", "inconclusive"}


# --- phase bands ----------------------------------------------------------------
def _phase(con, title, start, due):
    from renv.research import plan
    return plan.add_item(con, "p", title, kind="phase", start=start, due=due)


def test_bands_membership_and_order(tmp_path):
    con = _proj(tmp_path)
    p1 = _phase(con, "ideation", "2026-07-01", "2026-07-20")
    p2 = _phase(con, "toy experiments", "2026-07-21", "2026-08-10")
    phases.set_band(con, p1["id"], 0, 500)
    phases.set_band(con, p2["id"], 500, 1200)
    pid = db.project_id(con, "p")
    con.execute("INSERT INTO graph_layout (project_id, node_id, x, y) VALUES (?,?,?,?)",
                (pid, "claim:1", 100, 0))       # center 210 → band 1
    con.execute("INSERT INTO graph_layout (project_id, node_id, x, y) VALUES (?,?,?,?)",
                (pid, "exp:1", 600, 0))         # center 710 → band 2
    con.commit()
    m = phases.membership(con, "p")
    assert m["claim:1"] == p1["id"] and m["exp:1"] == p2["id"]
    assert phases.ordinals(con, "p") == {p1["id"]: 0, p2["id"]: 1}


def test_band_rules(tmp_path):
    con = _proj(tmp_path)
    from renv.research import plan
    m = plan.add_item(con, "p", "AAAI", kind="deadline", due="2026-08-01")
    with pytest.raises(ValueError):
        phases.set_band(con, m["id"], 0, 400)      # only phases carry bands
    p1 = _phase(con, "x", None, "2026-08-01")
    with pytest.raises(ValueError):
        phases.set_band(con, p1["id"], 0, 40)      # too narrow
    phases.set_band(con, p1["id"], 0, 400)
    phases.set_color(con, p1["id"], "violet")
    assert phases.list_phases(con, "p")[0]["color"] == "violet"
    phases.set_color(con, p1["id"], "")            # back to auto
    with pytest.raises(ValueError):
        phases.set_color(con, p1["id"], "mauve")
    phases.clear_band(con, p1["id"])
    assert phases.list_phases(con, "p")[0]["x0"] is None


# --- the lint catalog ------------------------------------------------------------
def test_lint_headline_unbacked_and_adjudication_suppression(tmp_path):
    from renv.research import finding as findmod
    con = _proj(tmp_path)
    claim.add_claim(con, "p", "our grand thesis", kind="thesis")
    out = lint.run(con, "p")
    hits = [f for f in out["open"] if f["rule"] == "headline-unbacked"]
    assert len(hits) == 1
    # carried, not duplicated, on the second run
    out2 = lint.run(con, "p")
    assert out2["opened"] == 0 and out2["carried"] >= 1
    # a rejection silences the nag forever
    findmod.adjudicate(con, hits[0]["id"], "reject", "intentionally open until phase 2")
    out3 = lint.run(con, "p")
    assert not [f for f in out3["open"] if f["rule"] == "headline-unbacked"]
    assert out3["suppressed"] >= 1


def test_lint_toy_only_support_and_autoresolve(tmp_path):
    con = _proj(tmp_path)
    run = _run(con, tmp_path)
    c = claim.add_claim(con, "p", "big result", kind="contribution")
    out = claim.link_evidence(con, c["id"], run_id=run["id"], stance="supports",
                              grade="suggestive")
    assert [f for f in lint.run(con, "p")["open"] if f["rule"] == "toy-only-support"]
    claim.link_evidence(con, c["id"], run_id=run["id"], stance="supports",
                        grade="confirmatory")
    out = lint.run(con, "p")
    assert not [f for f in out["open"] if f["rule"] == "toy-only-support"]
    assert out["resolved"] >= 1


def test_lint_exploratory_only(tmp_path):
    con = _proj(tmp_path)
    run = _run(con, tmp_path)
    c = claim.add_claim(con, "p", "post-hoc special", kind="contribution")
    claim.link_evidence(con, c["id"], run_id=run["id"], stance="supports",
                        grade="confirmatory")
    assert [f for f in lint.run(con, "p")["open"] if f["rule"] == "exploratory-only"]


def test_lint_stale_and_hypothesis_untested(tmp_path):
    con = _proj(tmp_path)
    cit = _cite(con)
    c = claim.add_claim(con, "p", "wording v1", kind="assertion")
    claim.link_evidence(con, c["id"], citation_id=cit["id"], stance="supports")
    claim.update_text(con, c["id"], "wording v2 — stronger")
    claim.add_claim(con, "p", "untested hunch", kind="hypothesis")
    rules = {f["rule"] for f in lint.run(con, "p")["open"]}
    assert "stale-evidence" in rules and "hypothesis-untested" in rules


def test_lint_phase_direction(tmp_path):
    con = _proj(tmp_path)
    p1 = _phase(con, "early", "2026-07-01", "2026-07-20")
    p2 = _phase(con, "late", "2026-07-21", "2026-08-10")
    phases.set_band(con, p1["id"], 0, 500)
    phases.set_band(con, p2["id"], 500, 1200)
    q = log.add_entry(con, "p", "question", "q late")
    experiment.create_experiment(con, "p", "001")
    exp_id = con.execute("SELECT id FROM experiment WHERE slug='001'").fetchone()["id"]
    links.add_link(con, "p", from_kind="question", from_id=q["id"],
                   to_kind="experiment", to_id=exp_id, relation="motivates")
    pid = db.project_id(con, "p")
    # question sits in the LATE band, the experiment it motivates in the EARLY one
    con.execute("INSERT INTO graph_layout (project_id, node_id, x, y) VALUES (?,?,?,?)",
                (pid, f"log:{q['id']}", 700, 0))
    con.execute("INSERT INTO graph_layout (project_id, node_id, x, y) VALUES (?,?,?,?)",
                (pid, f"exp:{exp_id}", 100, 0))
    con.commit()
    assert [f for f in lint.run(con, "p")["open"] if f["rule"] == "phase-direction"]


def test_lint_result_without_run_via_backdoor(tmp_path):
    con = _proj(tmp_path)
    pid = db.project_id(con, "p")
    con.execute("INSERT INTO log_entry (project_id, type, ts, body_md) "
                "VALUES (?, 'result', 'now', 'made-up number')", (pid,))
    con.commit()
    assert [f for f in lint.run(con, "p")["open"] if f["rule"] == "result-without-run"]
