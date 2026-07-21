"""Per-section paper critique (Pillar 8) — automated checks + a rubric.

The valuable, high-signal checks are *automated*: they cross-reference the draft
against the single source of truth (metric rows, verified citations, the bib) and
return facts, not opinions — e.g. an abstract number with no matching metric, or a
``\\spancite`` that does not verify as full support. These run with no model and
gate a release.

The rubric (RUBRIC) is data: section → checks with a dimension, severity, and a
``verify`` mode. The ``automated`` checks are implemented here; the ``llm`` checks
are consumed by the agentic review layer (a Claude Code skill/Workflow) which fans
out one finder per (section × dimension), adversarially verifies each finding, and
synthesizes a report. Both write findings in the same shape.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from renv.research import experiment
from renv.research.db import now

# The rubric — checks are data. `automated` ones are implemented below.
RUBRIC = [
    {"id": "abs-claims-match-metrics", "section": "abstract", "dimension": "correctness",
     "severity": "high", "verify": "automated",
     "check": "Every quantitative claim in the abstract matches a metric row from a run."},
    {"id": "cites-verify-full", "section": "all", "dimension": "correctness",
     "severity": "high", "verify": "automated",
     "check": "Every \\spancite resolves to a citation that verifies as full support."},
    {"id": "bib-coverage", "section": "all", "dimension": "completeness",
     "severity": "medium", "verify": "automated",
     "check": "Every cited key has an entry in references.bib."},
    {"id": "results-table-fresh", "section": "results", "dimension": "reproducibility",
     "severity": "high", "verify": "automated",
     "check": "results_table.tex is generated and reflects current metric rows."},
    {"id": "exp-have-hypotheses", "section": "experiments", "dimension": "rigor",
     "severity": "low", "verify": "automated",
     "check": "Every experiment states a hypothesis."},
    {"id": "claims-have-evidence", "section": "all", "dimension": "rigor",
     "severity": "medium", "verify": "automated",
     "check": "Every thesis/contribution claim has supporting (or refuting) evidence."},
    # llm-verified checks (handled by the agentic layer, listed here for coverage):
    {"id": "rw-positioning-explicit", "section": "related_work", "dimension": "novelty",
     "severity": "high", "verify": "llm",
     "check": "The delta vs. each cited prior work is stated, not just summarized."},
    {"id": "method-reproducible", "section": "method", "dimension": "reproducibility",
     "severity": "medium", "verify": "llm",
     "check": "The method is described in enough detail to reproduce."},
]

_NUM = re.compile(r"\d+\.\d+%?|\d+%")           # decimals + percentages, not bare ints
_SPANCITE = re.compile(r"\\spancite\{([^}]*)\}\{(\d+)\}\{(\d+)\}")
_CITE = re.compile(r"\\cite[tp]?\{([^}]*)\}")
_BIBKEY = re.compile(r"@\w+\{([^,]+),")
_ABSTRACT = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)


def _finding(check, issue, *, location=None, verified=True):
    return {"check_id": check["id"], "section": check["section"],
            "dimension": check["dimension"], "severity": check["severity"],
            "verify_mode": check["verify"], "verified": verified,
            "issue": issue, "location": location}


def _by_id(cid):
    return next(c for c in RUBRIC if c["id"] == cid)


def _num(token: str) -> float:
    return float(token.rstrip("%"))


# --- automated checks --------------------------------------------------------
def _metric_values(con, project):
    rows = experiment.list_experiments(con, project)
    return [v for r in rows for v in (r["metrics"] or {}).values()
            if isinstance(v, (int, float))]


def _check_abstract_numbers(con, project, tex):
    """Flag decimal/percent numbers in the prose that match no metric row.

    Scans the WHOLE manuscript (not just the abstract) so a fabricated number
    anywhere is caught; citation/ref args are stripped first to avoid false hits.
    Matching is value-or-×100 (a 0.82 metric matches "0.82" or "82%"). This is a
    coincidence check, not identity — a flagged number may be a legitimate prose
    constant (e.g. a p-value); reject it once and adjudication won't re-raise it.
    """
    body = re.sub(r"\\(spancite|cite[tp]?|ref|input|bibliography)\{[^}]*\}", " ", tex)
    values = _metric_values(con, project)
    out = []
    for tok in sorted(set(_NUM.findall(body))):
        x = _num(tok)
        if any(abs(v - x) < 1e-6 or abs(v * 100 - x) < 1e-6 for v in values):
            continue
        out.append(_finding(_by_id("abs-claims-match-metrics"),
                            f"number {tok!r} in the text matches no metric row",
                            location={"section": "body", "quote": tok}))
    return out


def _check_spancite_support(con, project, tex):
    from renv.papers import ingest
    cites = {(c["source_id"], c["src_start"]): c
             for c in ingest.citations_for_project(con, project)}
    out = []
    for key, start, _end in _SPANCITE.findall(tex):
        c = cites.get((key, int(start)))
        if c is None:
            out.append(_finding(_by_id("cites-verify-full"),
                                f"\\spancite{{{key}}}{{{start}}} has no citation row in the store",
                                location={"quote": f"{key}:{start}"}))
        elif c.get("support") != "full":
            out.append(_finding(_by_id("cites-verify-full"),
                                f"citation {key}:{start} verifies as {c.get('support')!r}, not full",
                                location={"quote": f"{key}:{start}"}))
    return out


def _check_bib_coverage(project_root, tex):
    bib = Path(project_root) / "text" / "references.bib"
    have = set(_BIBKEY.findall(bib.read_text())) if bib.exists() else set()
    referenced = set(m[0] for m in _SPANCITE.findall(tex))
    for grp in _CITE.findall(tex):
        referenced |= {k.strip() for k in grp.split(",")}
    return [_finding(_by_id("bib-coverage"), f"cited key {k!r} has no references.bib entry",
                     location={"quote": k})
            for k in sorted(referenced - have)]


def _check_results_table_fresh(con, project, project_root):
    table = Path(project_root) / "text" / "results_table.tex"
    if not table.exists():
        return [_finding(_by_id("results-table-fresh"),
                         "results_table.tex missing — run `renv weave`")]
    text = table.read_text()
    out = []
    for r in experiment.list_experiments(con, project):
        for v in (r["metrics"] or {}).values():
            if isinstance(v, float) and f"{v:.3f}" not in text:
                out.append(_finding(_by_id("results-table-fresh"),
                                    f"metric {v:.3f} ({r['slug']}) not in results_table.tex — stale; run `renv weave`"))
    return out


def _check_experiment_hypotheses(con, project):
    return [_finding(_by_id("exp-have-hypotheses"),
                     f"experiment {r['slug']!r} has no hypothesis", location={"quote": r["slug"]})
            for r in experiment.list_experiments(con, project) if not r["hypothesis"]]


def _check_claims_supported(con, project):
    from renv.research import claim as claimmod
    return [_finding(_by_id("claims-have-evidence"),
                     f"{c['kind']} claim has no evidence: {c['text'][:60]!r}",
                     location={"quote": f"claim:{c['id']}"})
            for c in claimmod.list_claims(con, project)
            if c["kind"] in ("thesis", "contribution") and c["status"] == "open"]


# --- driver ------------------------------------------------------------------
def run_automated(con: sqlite3.Connection, root, project: str) -> list[dict]:
    proot = Path(root) / "projects" / project
    paper = proot / "text" / "paper.tex"
    if not paper.exists():
        return [_finding(_by_id("results-table-fresh"),
                         "no text/paper.tex — run `renv draft`")]
    tex = paper.read_text()
    return (_check_abstract_numbers(con, project, tex)
            + _check_spancite_support(con, project, tex)
            + _check_bib_coverage(proot, tex)
            + _check_results_table_fresh(con, project, proot)
            + _check_experiment_hypotheses(con, project)
            + _check_claims_supported(con, project))


def render_report(project: str, findings: list[dict], suppressed: list[dict] | None = None) -> str:
    order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted(findings, key=lambda f: order.get(f["severity"], 3))
    suppressed = suppressed or []
    lines = [f"# Review — {project} ({now()[:10]})", "",
             f"{len(findings)} open finding(s); {len(suppressed)} previously dismissed. "
             "LLM-verified checks (positioning, reproducibility) run via the review skill.", ""]
    if not findings:
        lines.append("✓ No new automated findings.")
    for f in findings:
        loc = f.get("location") or {}
        where = f" [{loc.get('quote')}]" if loc.get("quote") else ""
        fid = f" (#{f['id']})" if f.get("id") else ""
        lines.append(f"- **{f['severity'].upper()}**{fid} ({f['dimension']}/{f['check_id']}): "
                     f"{f['issue']}{where}  — adjudicate: `renv finding accept/reject {f.get('id', '?')}`")
    if suppressed:
        lines += ["", "## Previously dismissed (not re-raised)"]
        for f in suppressed:
            lines.append(f"- ~~{f['check_id']}: {f['issue']}~~ — rejected: {f['prior_reason']}")
    return "\n".join(lines) + "\n"


def review(con: sqlite3.Connection, root, project: str) -> dict:
    from renv.research import finding as findmod
    findings = run_automated(con, root, project)
    persisted = findmod.persist_findings(con, project, findings)
    # auto-resolve prior findings whose condition no longer fires
    live = {findmod.fingerprint(f) for f in findings}
    findmod.resolve_fixed(con, project, live)

    proot = Path(root) / "projects" / project
    rdir = proot / "reviews"
    rdir.mkdir(parents=True, exist_ok=True)
    out = rdir / f"{now()[:10]}.md"
    out.write_text(render_report(project, persisted["open"], persisted["suppressed"]))
    return {"open": persisted["open"], "suppressed": persisted["suppressed"],
            "report": str(out)}
