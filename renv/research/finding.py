"""Review findings as persistent, branchable, adjudicable nodes (Pillar 8).

A `renv review` / `renv lint` persists each finding as a node you (or an agent)
can investigate and rule on. From a finding you can branch into the proof it
cited (`finding_evidence`), then **accept** or **reject** it with reasoning.

Most findings are waivable: a reject is remembered by fingerprint and a future
run does not re-raise it (that stops coincidence nags and hallucinated LLM
findings from piling up). Provenance findings in `NON_WAIVABLE` cannot be
dismissed — `adjudicate(..., reject)` raises, persist/lint will not suppress
them, and a row that is already `rejected` is reopened rather than duplicated.

Fingerprint = stable identity of a finding (check + section + the anchored
location), independent of incidental wording, so "the same issue" is recognized
across review runs. Lint fingerprints are `hash(["lint", rule, entity])`.
"""

from __future__ import annotations

import json
import sqlite3

from renv.research.db import canonical_hash, now, project_id, row_to_dict

_STATUS_FOR = {"accept": "accepted", "reject": "rejected", "defer": "open"}

# Provenance holes: the manuscript or graph is claiming something the store
# cannot back. Coincidence leftovers (unmatched prose numbers) stay waivable.
NON_WAIVABLE = frozenset({
    "cites-verify-full",
    "results-table-fresh",
    "bib-known-paper",
    "lint-support-verdict-none",
    "lint-result-without-run",
})


def is_non_waivable(check_id: str | None) -> bool:
    return (check_id or "") in NON_WAIVABLE


def fingerprint(f: dict) -> str:
    loc = (f.get("location") or {}).get("quote")
    return canonical_hash([f.get("check_id"), f.get("section"), loc or f.get("issue")])


def rejected_reasons(con: sqlite3.Connection, pid: int) -> dict[str, str]:
    """fingerprint -> latest rejection reasoning, for findings previously dismissed."""
    rows = con.execute(
        "SELECT f.fingerprint AS fp, a.reasoning AS reason, a.id AS aid "
        "FROM finding f JOIN adjudication a ON a.finding_id=f.id "
        "WHERE f.project_id=? AND f.status='rejected' ORDER BY a.id", (pid,)
    ).fetchall()
    return {r["fp"]: r["reason"] for r in rows}  # later rows win → latest reasoning


def _link_evidence(con: sqlite3.Connection, finding_id: int, f: dict) -> None:
    """Best-effort: attach the citation a finding is about, so you can branch into it."""
    loc = (f.get("location") or {}).get("quote") or ""
    if ":" not in loc:
        return
    key, _, start = loc.partition(":")
    if not start.isdigit():
        return
    row = con.execute(
        "SELECT c.id FROM citation c JOIN paper p ON p.id=c.paper_id "
        "WHERE p.key=? AND c.src_start=?", (key, int(start))
    ).fetchone()
    if row:
        con.execute("INSERT INTO finding_evidence (finding_id, citation_id, note) "
                    "VALUES (?,?,?)", (finding_id, row["id"], "cited span"))


def reopen_rejected(con: sqlite3.Connection, pid: int, fp: str) -> int | None:
    """Re-open the latest rejected row with this fingerprint; None if none exists."""
    row = con.execute(
        "SELECT id FROM finding WHERE project_id=? AND fingerprint=? "
        "AND status='rejected' ORDER BY id DESC LIMIT 1", (pid, fp)
    ).fetchone()
    if not row:
        return None
    con.execute("UPDATE finding SET status='open' WHERE id=?", (row["id"],))
    return row["id"]


def persist_findings(con: sqlite3.Connection, project: str, findings: list[dict]) -> dict:
    """Insert open findings, suppressing waivable ones previously rejected.

    Non-waivable fingerprints are never suppressed; a rejected row is reopened
    instead of inserting a duplicate.
    """
    pid = project_id(con, project)
    rejected = rejected_reasons(con, pid)
    rr = con.execute(
        "INSERT INTO review_run (project_id, ts) VALUES (?,?)", (pid, now())
    ).lastrowid

    open_, suppressed = [], []
    for f in findings:
        fp = fingerprint(f)
        if fp in rejected and not is_non_waivable(f.get("check_id")):
            suppressed.append({**f, "fingerprint": fp, "prior_reason": rejected[fp]})
            continue
        existing = con.execute(
            "SELECT id FROM finding WHERE project_id=? AND fingerprint=? "
            "AND status IN ('open','accepted') LIMIT 1", (pid, fp)
        ).fetchone()
        if existing:                       # same live finding — don't duplicate
            open_.append({**f, "id": existing["id"], "fingerprint": fp, "carried": True})
            continue
        if is_non_waivable(f.get("check_id")):
            rid = reopen_rejected(con, pid, fp)
            if rid is not None:
                open_.append({**f, "id": rid, "fingerprint": fp, "reopened": True})
                continue
        fid = con.execute(
            "INSERT INTO finding (project_id, review_run_id, fingerprint, check_id, "
            "section, dimension, severity, issue, location_json, created) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, rr, fp, f.get("check_id"), f.get("section"), f.get("dimension"),
             f.get("severity"), f.get("issue"), json.dumps(f.get("location") or {}), now()),
        ).lastrowid
        _link_evidence(con, fid, f)
        open_.append({**f, "id": fid, "fingerprint": fp})

    con.execute("UPDATE review_run SET n_open=?, n_suppressed=? WHERE id=?",
                (len(open_), len(suppressed), rr))
    con.commit()
    return {"review_run": rr, "open": open_, "suppressed": suppressed}


def list_findings(con: sqlite3.Connection, project: str, *, status: str | None = None) -> list[dict]:
    pid = project_id(con, project)
    sql = "SELECT * FROM finding WHERE project_id=?"
    params = [pid]
    if status:
        sql += " AND status=?"
        params.append(status)
    return [row_to_dict(r) for r in con.execute(sql + " ORDER BY id", params).fetchall()]


def get_finding(con: sqlite3.Connection, finding_id: int) -> dict | None:
    """A finding with its evidence (the proof to branch into) and adjudication trail."""
    f = row_to_dict(con.execute("SELECT * FROM finding WHERE id=?", (finding_id,)).fetchone())
    if not f:
        return None
    f["location"] = json.loads(f.pop("location_json") or "{}")
    f["evidence"] = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM finding_evidence WHERE finding_id=?", (finding_id,)).fetchall()]
    f["adjudications"] = [row_to_dict(r) for r in con.execute(
        "SELECT * FROM adjudication WHERE finding_id=? ORDER BY id", (finding_id,)).fetchall()]
    return f


def adjudicate(con: sqlite3.Connection, finding_id: int, verdict: str,
               reasoning: str, *, by: str = "agent") -> dict:
    """Rule on a finding. Reasoning is required so future agents understand the call.

    Reject is refused for `NON_WAIVABLE` check_ids — fix the evidence instead.
    """
    if verdict not in _STATUS_FOR:
        raise ValueError(f"verdict must be accept/reject/defer, got {verdict!r}")
    if not (reasoning or "").strip():
        raise ValueError("a verdict requires reasoning (future agents must see why)")
    row = con.execute("SELECT check_id FROM finding WHERE id=?", (finding_id,)).fetchone()
    if not row:
        raise KeyError(f"no finding #{finding_id}")
    if verdict == "reject" and is_non_waivable(row["check_id"]):
        raise ValueError(
            f"finding #{finding_id} ({row['check_id']}) is non-waivable — "
            "fix the evidence; reject is refused")
    con.execute(
        "INSERT INTO adjudication (finding_id, verdict, reasoning, by, ts) VALUES (?,?,?,?,?)",
        (finding_id, verdict, reasoning, by, now()))
    con.execute("UPDATE finding SET status=? WHERE id=?",
                (_STATUS_FOR[verdict], finding_id))
    con.commit()
    return get_finding(con, finding_id)


def resolve_fixed(con: sqlite3.Connection, project: str, live_fingerprints: set[str],
                  *, family: str = "review") -> int:
    """Mark open/accepted findings whose condition no longer fires as 'resolved'.

    family='review' ignores lint-* rows (owned by lint.run); family='lint' only those.
    Mixing the two would let `renv review` silently resolve graph lints and vice versa.
    """
    if family not in ("review", "lint"):
        raise ValueError(f"family must be review|lint, got {family!r}")
    pid = project_id(con, project)
    extra = ("AND check_id LIKE 'lint-%'" if family == "lint"
             else "AND check_id NOT LIKE 'lint-%'")
    rows = con.execute(
        f"SELECT id, fingerprint FROM finding WHERE project_id=? "
        f"AND status IN ('open','accepted') {extra}", (pid,)).fetchall()
    n = 0
    for r in rows:
        if r["fingerprint"] not in live_fingerprints:
            con.execute("UPDATE finding SET status='resolved' WHERE id=?", (r["id"],))
            n += 1
    con.commit()
    return n
