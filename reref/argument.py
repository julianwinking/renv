"""Argument analysis — does the claim graph actually hold, and what's next?

A read-time lens over the claim/relation graph. It never writes: ``claim.status``
stays the LOCAL, evidence-derived truth of each claim. This module adds the
STRUCTURAL view the status field can't express:

- **foundation** — walk the ``depends_on`` DAG: a claim whose lemmas are
  refuted (or transitively broken) has a *broken* foundation even if its own
  evidence supports it. `sound` / `weak` (a lemma is still open) / `broken`.
  A warning, not a truth-flip — research dependency is argumentative support,
  not entailment.
- **contradictions** — two ``supported`` claims joined by a ``contradicts``
  edge are an internal inconsistency: a crisis the human loses track of.
- **frontier** — the open, thesis-critical claims ranked with a concrete next
  step. The compass: not "what's open" but "what to work on and how".
"""

from __future__ import annotations

import sqlite3

from . import claim as claimmod

_ORDER = {"sound": 0, "weak": 1, "broken": 2}


def analyze(con: sqlite3.Connection, project: str) -> dict:
    claims = {c["id"]: c for c in claimmod.list_claims(con, project)}
    depends: dict[int, list[int]] = {}
    contradicts: list[tuple[int, int]] = []
    for r in claimmod.list_relations(con, project):
        if r["kind"] == "depends_on":
            depends.setdefault(r["claim_id"], []).append(r["related_id"])
        elif r["kind"] == "contradicts":
            contradicts.append((r["claim_id"], r["related_id"]))

    # --- foundation via the depends_on DAG (acyclic; guarded at write time) ---
    memo: dict[int, tuple[str | None, list[int]]] = {}

    def foundation(cid: int) -> tuple[str | None, list[int]]:
        if cid in memo:
            return memo[cid]
        memo[cid] = ("sound", [])          # cycle backstop (shouldn't trigger)
        deps = depends.get(cid, [])
        if not deps:
            memo[cid] = (None, [])          # nothing to undermine
            return memo[cid]
        level, issues = "sound", []
        for d in deps:
            dc = claims.get(d)
            if not dc:
                continue
            dfound, _ = foundation(d)
            if dc["status"] == "refuted" or dfound == "broken":
                lvl = "broken"; issues.append(d)
            elif dc["status"] == "open" or dfound == "weak":
                lvl = "weak"
                if dc["status"] == "open":
                    issues.append(d)
            else:
                lvl = "sound"
            if _ORDER[lvl] > _ORDER[level]:
                level = lvl
        memo[cid] = (level, issues)
        return memo[cid]

    # --- "critical to a thesis" = in the transitive depends_on closure of a thesis ---
    critical: set[int] = set()

    def collect(cid: int) -> None:
        for d in depends.get(cid, []):
            if d not in critical:
                critical.add(d)
                collect(d)

    for cid, c in claims.items():
        if c["kind"] == "thesis":
            collect(cid)

    out_claims = []
    for cid, c in claims.items():
        f, issues = foundation(cid)
        out_claims.append({**c, "foundation": f, "foundation_issues": issues,
                           "critical_to_thesis": cid in critical})

    # --- contradictions among supported claims ---
    crises = []
    for a, b in contradicts:
        ca, cb = claims.get(a), claims.get(b)
        if ca and cb and ca["status"] == "supported" and cb["status"] == "supported":
            crises.append({"a": a, "b": b, "a_text": ca["text"], "b_text": cb["text"]})

    # --- frontier: open, critical claims + the next concrete step ---
    def criticality(c) -> int:
        if c["kind"] == "thesis":
            return 3
        if c["id"] in critical:
            return 2
        if c["kind"] == "contribution":
            return 1
        return 0

    frontier = []
    for c in out_claims:
        if c["status"] == "supported":
            continue
        if c["kind"] not in ("thesis", "contribution") and c["id"] not in critical:
            continue
        ev = c["evidence_count"]
        if c["status"] == "refuted":
            step = "Refuted — revise the claim or the experiment behind it"
        elif ev == 0:
            step = "No evidence yet — link a run or a citation"
        else:
            step = "Has evidence but isn't backed — the runs/citations don't support it; add or revise"
        if c["foundation"] == "broken":
            step += " · foundation broken (a lemma it rests on is refuted)"
        frontier.append({
            "id": c["id"], "text": c["text"], "kind": c["kind"], "status": c["status"],
            "criticality": criticality(c), "critical_to_thesis": c["critical_to_thesis"],
            "evidence_count": ev, "next": step,
        })
    # most critical first; among equals, closest-to-done (more evidence) first
    frontier.sort(key=lambda x: (-x["criticality"], -x["evidence_count"]))

    return {
        "claims": out_claims,
        "contradictions": crises,
        "frontier": frontier,
        "summary": {
            "open_critical": len(frontier),
            "contradictions": len(crises),
            "broken_foundations": sum(1 for c in out_claims if c["foundation"] == "broken"),
            "weak_foundations": sum(1 for c in out_claims if c["foundation"] == "weak"),
        },
    }
