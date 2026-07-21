"""Graph lints — the invariant catalog, delivered through the finding machinery.

`log.check_invariants` guards §0 (a result needs a run). This module is the
full catalog: every rule is a query over the store that yields *violations* —
places where the research graph claims more than it can back, or where
structure has gone stale. Violations are persisted as findings, which buys the
whole adjudication apparatus for free: fingerprint dedup across runs, a
rejected verdict suppresses the same nag forever ("yes, this thesis is
intentionally open for now"), and violations that stop firing auto-resolve.

Severities follow the review rubric: high / medium / low.
"""

from __future__ import annotations

import sqlite3

from renv.research import finding as findmod
from renv.research import links as linksmod
from renv.research import phases as phasesmod
from renv.research.db import canonical_hash, now, project_id

# relations that express forward motion — they should point rightward (to the
# same or a later phase) when both endpoints sit in placed bands
_FORWARD = ("motivates", "raises", "informs", "suggests")

_HEADLINE = ("thesis", "contribution")


# --- rules: each returns a list of {entity, issue} ---------------------------
def _r_result_without_run(con, pid):
    return [{"entity": f"log:{r['id']}",
             "issue": "a 'result' entry has no run evidence (§0)"}
            for r in con.execute(
                "SELECT le.id FROM log_entry le WHERE le.project_id=? "
                "AND le.type='result' AND NOT EXISTS (SELECT 1 FROM log_evidence ev "
                "WHERE ev.log_entry_id=le.id AND ev.run_id IS NOT NULL)", (pid,))]


def _r_headline_unbacked(con, pid):
    return [{"entity": f"claim:{r['id']}",
             "issue": f"{r['kind']} claim is open with no evidence: “{r['text'][:80]}”"}
            for r in con.execute(
                "SELECT id, kind, text FROM claim WHERE project_id=? AND status='open' "
                f"AND kind IN {_HEADLINE} AND NOT EXISTS (SELECT 1 FROM claim_evidence "
                "ev WHERE ev.claim_id=claim.id AND ev.retracted IS NULL)", (pid,))]


def _r_support_verdict_none(con, pid):
    return [{"entity": f"evidence:{r['id']}",
             "issue": f"claim #{r['claim_id']} is 'supported' by citation "
                      f"#{r['citation_id']} whose verifier verdict is 'none' — "
                      "the span does not entail the claim"}
            for r in con.execute(
                "SELECT ev.id, ev.claim_id, ev.citation_id FROM claim_evidence ev "
                "JOIN claim c ON c.id=ev.claim_id JOIN citation ci ON ci.id=ev.citation_id "
                "WHERE c.project_id=? AND ev.retracted IS NULL AND ev.stance='supports' "
                "AND ci.support='none'", (pid,))]


def _r_toy_only_support(con, pid):
    return [{"entity": f"claim:{r['id']}",
             "issue": f"{r['kind']} claim is 'supported' but no supporting evidence is "
                      f"confirmatory-grade: “{r['text'][:80]}” — scale the experiment "
                      "or soften the claim"}
            for r in con.execute(
                "SELECT id, kind, text FROM claim WHERE project_id=? AND status='supported' "
                f"AND kind IN {_HEADLINE} AND NOT EXISTS (SELECT 1 FROM claim_evidence ev "
                "WHERE ev.claim_id=claim.id AND ev.retracted IS NULL "
                "AND ev.stance='supports' AND ev.grade='confirmatory')", (pid,))]


def _r_supported_contradiction(con, pid):
    return [{"entity": f"relation:{r['id']}",
             "issue": f"claims #{r['claim_id']} and #{r['related_id']} are BOTH "
                      "'supported' yet marked as contradicting — an internal "
                      "inconsistency; at least one evidence base is wrong"}
            for r in con.execute(
                "SELECT cr.id, cr.claim_id, cr.related_id FROM claim_relation cr "
                "JOIN claim a ON a.id=cr.claim_id JOIN claim b ON b.id=cr.related_id "
                "WHERE cr.kind='contradicts' AND a.project_id=? "
                "AND a.status='supported' AND b.status='supported'", (pid,))]


def _r_done_experiment_no_runs(con, pid):
    return [{"entity": f"exp:{r['id']}",
             "issue": f"experiment '{r['slug']}' is marked done but has no completed run"}
            for r in con.execute(
                "SELECT id, slug FROM experiment WHERE project_id=? AND status='done' "
                "AND NOT EXISTS (SELECT 1 FROM run WHERE run.experiment_id=experiment.id "
                "AND run.status='done')", (pid,))]


def _r_dangling_question(con, pid):
    return [{"entity": f"log:{r['id']}",
             "issue": f"open question has no answer and motivates no experiment: "
                      f"“{r['body_md'][:80]}”"}
            for r in con.execute(
                "SELECT id, body_md FROM log_entry le WHERE project_id=? AND type='question' "
                "AND NOT EXISTS (SELECT 1 FROM log_entry a WHERE a.answers=le.id) "
                "AND NOT EXISTS (SELECT 1 FROM context_link cl WHERE cl.from_kind='question' "
                "AND cl.from_id=le.id AND cl.relation='motivates')", (pid,))]


def _r_exploratory_only(con, pid):
    return [{"entity": f"claim:{r['id']}",
             "issue": f"{r['kind']} claim is 'supported' only by exploratory (post-hoc) "
                      f"run evidence — no run came from an experiment that declared it "
                      f"as tested: “{r['text'][:80]}”"}
            for r in con.execute(
                "SELECT id, kind, text FROM claim c WHERE project_id=? AND status='supported' "
                f"AND kind IN {_HEADLINE} "
                "AND EXISTS (SELECT 1 FROM claim_evidence ev WHERE ev.claim_id=c.id "
                "  AND ev.retracted IS NULL AND ev.stance='supports' AND ev.run_id IS NOT NULL) "
                "AND NOT EXISTS (SELECT 1 FROM claim_evidence ev WHERE ev.claim_id=c.id "
                "  AND ev.retracted IS NULL AND ev.stance='supports' "
                "  AND ev.run_id IS NOT NULL AND ev.preregistered=1)", (pid,))]


def _r_stale_evidence(con, pid):
    return [{"entity": f"evidence:{r['id']}",
             "issue": f"claim #{r['claim_id']}'s wording changed after this evidence was "
                      "attached — re-confirm it still applies, or retract it"}
            for r in con.execute(
                "SELECT ev.id, ev.claim_id FROM claim_evidence ev JOIN claim c "
                "ON c.id=ev.claim_id WHERE c.project_id=? AND ev.stale=1 "
                "AND ev.retracted IS NULL", (pid,))]


def _r_hypothesis_untested(con, pid):
    return [{"entity": f"claim:{r['id']}",
             "issue": f"hypothesis has no experiment declared to test it: "
                      f"“{r['text'][:80]}” — declare a test or park it as a question"}
            for r in con.execute(
                "SELECT id, text FROM claim WHERE project_id=? AND kind='hypothesis' "
                "AND status='open' AND NOT EXISTS (SELECT 1 FROM experiment_test t "
                "WHERE t.claim_id=claim.id)", (pid,))]


def _make_project_rules(project):
    """Rules needing the project slug (they call domain modules, not raw SQL)."""

    def _r_dangling_context_link(con, pid):
        return [{"entity": f"link:{lk['id']}",
                 "issue": f"context link #{lk['id']} points at a deleted entity "
                          f"({lk['missing']}) — the graph silently hides this edge"}
                for lk in linksmod.find_dangling(con, project)]

    def _r_phase_direction(con, pid):
        member = phasesmod.membership(con, project)
        order = phasesmod.ordinals(con, project)
        if not order:
            return []
        out = []
        for lk in linksmod.list_links(con, project):
            if lk["relation"] not in _FORWARD:
                continue
            a = member.get(linksmod.graph_node_id(lk["from_kind"], lk["from_id"]))
            b = member.get(linksmod.graph_node_id(lk["to_kind"], lk["to_id"]))
            if a is None or b is None or order.get(a, 0) <= order.get(b, 0):
                continue
            out.append({"entity": f"link:{lk['id']}",
                        "issue": f"'{lk['relation']}' edge points backward across phases "
                                 f"({lk['from_kind']} #{lk['from_id']} → {lk['to_kind']} "
                                 f"#{lk['to_id']}) — forward motion should read left→right"})
        return out

    def _r_phase_monotonic(con, pid):
        member = phasesmod.membership(con, project)
        order = phasesmod.ordinals(con, project)
        if not order:
            return []
        out = []
        for r in con.execute(
                "SELECT id, slug, parent_id FROM experiment "
                "WHERE project_id=? AND parent_id IS NOT NULL", (pid,)):
            child = member.get(f"exp:{r['id']}")
            parent = member.get(f"exp:{r['parent_id']}")
            if child is None or parent is None:
                continue
            if order.get(child, 0) < order.get(parent, 0):
                out.append({"entity": f"exp:{r['id']}",
                            "issue": f"experiment '{r['slug']}' sits in an earlier phase "
                                     "than the experiment it branches from — a follow-up "
                                     "cannot precede its parent"})
        return out

    def _r_band_date_order(con, pid):
        placed = [p for p in phasesmod.list_phases(con, project) if p["x0"] is not None]
        by_date = sorted(placed, key=lambda p: ((p["start"] or p["due"]), p["due"], p["id"]))
        out = []
        for canvas_pos, p in enumerate(placed):     # placed is already x0-ordered
            date_pos = by_date.index(p)
            if canvas_pos != date_pos:
                out.append({"entity": f"plan:{p['id']}",
                            "issue": f"phase “{p['title']}” sits at canvas position "
                                     f"{canvas_pos + 1} but is #{date_pos + 1} by date — "
                                     "the canvas order contradicts the timeline"})
        return out

    return [
        ("dangling-context-link", "medium", _r_dangling_context_link),
        ("phase-direction", "low", _r_phase_direction),
        ("phase-monotonic", "medium", _r_phase_monotonic),
        ("band-date-order", "low", _r_band_date_order),
    ]


RULES = [
    # (id, severity, fn(con, pid) -> violations)
    ("result-without-run", "high", _r_result_without_run),
    ("headline-unbacked", "medium", _r_headline_unbacked),
    ("support-verdict-none", "high", _r_support_verdict_none),
    ("toy-only-support", "medium", _r_toy_only_support),
    ("supported-contradiction", "high", _r_supported_contradiction),
    ("done-experiment-no-runs", "high", _r_done_experiment_no_runs),
    ("dangling-question", "low", _r_dangling_question),
    ("exploratory-only", "low", _r_exploratory_only),
    ("stale-evidence", "medium", _r_stale_evidence),
    ("hypothesis-untested", "low", _r_hypothesis_untested),
]


def _fingerprint(rule_id: str, entity: str) -> str:
    return canonical_hash(["lint", rule_id, entity])


def run(con: sqlite3.Connection, project: str) -> dict:
    """Run the catalog and sync violations into the finding table.

    - a new violation opens a finding (unless its fingerprint was rejected);
    - an unchanged violation carries its existing finding (no duplicates);
    - a violation that stopped firing auto-resolves its finding.
    Review findings (non-lint check_ids) are never touched.
    """
    pid = project_id(con, project)
    rejected = findmod.rejected_reasons(con, pid)

    live: dict[str, dict] = {}
    for rule_id, severity, fn in list(RULES) + _make_project_rules(project):
        for v in fn(con, pid):
            fp = _fingerprint(rule_id, v["entity"])
            live[fp] = {"rule": rule_id, "severity": severity, **v}

    opened, carried, suppressed = [], [], []
    for fp, v in live.items():
        if fp in rejected:
            suppressed.append({**v, "prior_reason": rejected[fp]})
            continue
        existing = con.execute(
            "SELECT id FROM finding WHERE project_id=? AND fingerprint=? "
            "AND status IN ('open','accepted') LIMIT 1", (pid, fp)).fetchone()
        if existing:
            carried.append({**v, "id": existing["id"]})
            continue
        fid = con.execute(
            "INSERT INTO finding (project_id, fingerprint, check_id, section, "
            "dimension, severity, issue, location_json, created) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, fp, f"lint-{v['rule']}", "graph", "lint", v["severity"],
             v["issue"], f'{{"entity": "{v["entity"]}"}}', now())).lastrowid
        opened.append({**v, "id": fid})

    resolved = 0
    for r in con.execute(
            "SELECT id, fingerprint FROM finding WHERE project_id=? "
            "AND check_id LIKE 'lint-%' AND status IN ('open','accepted')", (pid,)):
        if r["fingerprint"] not in live:
            con.execute("UPDATE finding SET status='resolved' WHERE id=?", (r["id"],))
            resolved += 1
    con.commit()
    return {"open": opened + carried, "opened": len(opened), "carried": len(carried),
            "suppressed": len(suppressed), "resolved": resolved}
