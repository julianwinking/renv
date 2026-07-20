"""A paper's reference list as first-class rows — the reader's citation map.

`build_references` parses the References section out of a corpus paper (numeric
[N] styles), extracts arXiv/DOI identifiers per entry, and matches entries
against the `paper` table. The viewer derives a traffic-light status per entry:

    library      — the cited paper is in the corpus (matched_paper_id set)
    not_relevant — the human reviewed it and dismissed it, with a comment
    unknown      — neither; a candidate to add or dismiss

Status is DERIVED (matched + verdict), never stored as a third column, and
human verdicts survive rebuilds via a normalized-raw fingerprint. In-text
markers ([12], [3,7], [1-4]) are computed on demand from the same parsed text
the index uses, so marker offsets share the coordinate system of citation
anchors. Papers added from the reader land in the INBOX (paper.inbox=1) until
the human marks them read — added-by-agent is not read-by-human.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from .db import now, row_to_dict
from .ingest import _ARXIV_RE, _DOI_RE, _http_get, _library_file, add as ingest_add

_HEAD_RE = re.compile(r"\n\s*(references|bibliography)\s*\n", re.IGNORECASE)
_ENTRY_RE = re.compile(r"\[(\d{1,3})\]")
# LNCS/Springer & friends number the reference LIST as "1." / "1)" at line
# starts while in-text citations stay bracketed — a second anchor style.
_ENTRY_DOT_RE = re.compile(r"^[ \t]*(\d{1,3})[.)][ \t]", re.MULTILINE)
_MARKER_RE = re.compile(r"\[(\d{1,3}(?:\s*[,–—-]\s*\d{1,3})*)\]")
_STOP_TITLE = {"the", "and", "for", "with", "from"}


def _fingerprint(raw: str) -> str:
    return hashlib.sha256(" ".join(raw.lower().split()).encode()).hexdigest()[:16]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower())


def _find_references_section(text: str) -> int | None:
    """Char offset where the references section body starts, or None.

    The LAST standalone 'References' heading wins — a ToC mention always
    precedes the real section, so recency is the guard."""
    best = None
    for m in _HEAD_RE.finditer(text):
        best = m.end()
    return best


_MAX_ENTRY = 1500       # a single reference entry never exceeds this
_MIN_ENTRY = 25         # below this the "entry" is column-scramble debris


def _candidate_entries(text: str, anchors: list[tuple[int, int]],
                       start_at: int) -> tuple[list[dict], int]:
    """Entries from the FIRST occurrence of each number at/after `start_at`,
    taken in document order — immune to pdfminer column scrambles that emit
    bare bracket clusters or blocks out of order. Returns (entries,
    substantive_count); the caller ranks candidates by how many entries carry
    real text. Validation: decent 1..N coverage and a plausible median entry
    length — in-text citation sequences fail both, because their "entries"
    span pages of body text."""
    first: dict[int, int] = {}
    for pos, num in anchors:
        if pos >= start_at and num not in first:
            first[num] = pos
    if not first:
        return [], 0
    # choose N as the largest number keeping 1..N coverage dense — one stray
    # "[400]" in body text must not dilute a 100-entry list below threshold
    nums_sorted = sorted(first)
    maxn, seen = 0, 0
    for n in nums_sorted:
        seen += 1
        if n <= 3 or seen / n >= 0.7:
            maxn = n
    present = [n for n in nums_sorted if n <= maxn]
    if maxn < 3 or len(present) / maxn < 0.7:
        return [], 0
    ordered = sorted((first[n], n) for n in present)
    # validate on UNCAPPED next-anchor distances: in-text citation sequences
    # have page-sized spacing that capping would hide
    gaps = sorted(ordered[i + 1][0] - ordered[i][0] for i in range(len(ordered) - 1))
    median = gaps[len(gaps) // 2] if gaps else 0
    if not (_MIN_ENTRY <= median <= _MAX_ENTRY):
        return [], 0
    entries: list[dict] = []
    for i, (pos, num) in enumerate(ordered):
        end = ordered[i + 1][0] if i + 1 < len(ordered) else len(text)
        end = min(end, pos + _MAX_ENTRY)
        entries.append({"num": num, "start": pos, "end": end,
                        "raw": text[pos:end].strip()})
    return entries, sum(1 for e in entries if len(e["raw"]) >= _MIN_ENTRY + 15)


def split_reference_entries(text: str) -> tuple[int | None, list[dict]]:
    """(section_start, [{num, raw, start, end}]) for numbered reference lists.

    Two anchor styles: bracketed "[N]" (IEEE/CVF) and line-start "N." / "N)"
    (LNCS/Springer, where only the in-text citations are bracketed). The
    'References' heading is a HINT, not an anchor — pdfminer's two-column
    extraction can emit entries before the heading, out of order, or with
    interleaved debris — so every occurrence of anchor #1 starts a candidate
    and the one with the most substantive entries wins (ties to the later
    start: reference lists live at the end)."""
    sec = _find_references_section(text)
    best: list[dict] = []
    best_score = 0
    for regex in (_ENTRY_RE, _ENTRY_DOT_RE):
        anchors = [(m.start(), int(m.group(1))) for m in regex.finditer(text)]
        for pos, num in anchors:
            if num != 1:
                continue
            run, score = _candidate_entries(text, anchors, pos)
            if score > best_score or (score == best_score and run and best and
                                      run[0]["start"] > best[0]["start"]):
                best, best_score = run, score
    if len(best) < 3:      # too short to be a bibliography — likely author-year
        return sec, []
    return sec if sec is not None else best[0]["start"], best


def find_markers(text: str, valid_nums: set[int], *, until: int | None = None) -> list[dict]:
    """In-text citation markers before the references section.

    Returns [{start, end, nums}] with ranges like [1-3] expanded; markers whose
    numbers are all unknown to the reference list are dropped (equation refs).
    """
    out = []
    for m in _MARKER_RE.finditer(text, 0, until if until is not None else len(text)):
        nums: list[int] = []
        for part in m.group(1).replace("–", "-").replace("—", "-").split(","):
            part = part.strip()
            a, dash, b = part.partition("-")
            if dash and a.strip().isdigit() and b.strip().isdigit():
                nums.extend(range(int(a.strip()), int(b.strip()) + 1))
            elif part.isdigit():
                nums.append(int(part))
        nums = [n for n in nums if n in valid_nums]
        if nums:
            out.append({"start": m.start(), "end": m.end(), "nums": nums})
    return out


def _match_paper(con: sqlite3.Connection, entry: dict) -> int | None:
    """Match a reference entry to a paper row: arxiv > doi > title tokens."""
    if entry.get("arxiv"):
        r = con.execute("SELECT id FROM paper WHERE arxiv=?", (entry["arxiv"],)).fetchone()
        if r:
            return r["id"]
    if entry.get("doi"):
        r = con.execute("SELECT id FROM paper WHERE lower(doi)=lower(?)",
                        (entry["doi"],)).fetchone()
        if r:
            return r["id"]
    raw = _norm(entry["raw"])
    for p in con.execute("SELECT id, title FROM paper WHERE title IS NOT NULL").fetchall():
        toks = [t for t in _norm(p["title"]).split()
                if len(t) > 3 and t not in _STOP_TITLE][:8]
        if len(toks) < 3:
            continue
        # short/generic titles ("Event-based vision: A survey") must match in
        # full — 3 common tokens like event/based/vision would fire on half the
        # bibliography; longer titles tolerate one hyphenation/OCR casualty
        need = len(toks) if len(toks) <= 4 else max(4, int(len(toks) * 0.8))
        if sum(t in raw for t in toks) >= need:
            return p["id"]
    return None


def build_references(con: sqlite3.Connection, root, key: str, *, parser: str = "auto") -> dict:
    """(Re)parse a corpus paper's reference list into paper_reference rows.

    Human verdicts survive the rebuild: rows are re-keyed by identifier or
    normalized-raw fingerprint and their verdict/comment carried over.
    """
    from .parse import parse
    paper = con.execute("SELECT id FROM paper WHERE key=?", (key,)).fetchone()
    if not paper:
        raise KeyError(f"no paper {key!r}")
    path = _library_file(Path(root), key)
    if path is None:
        raise ValueError(f"paper {key!r} has no full text in library/ — attach a PDF first")
    text = parse(path, parser).text
    sec, entries = split_reference_entries(text)
    old = {r["fingerprint"]: r for r in con.execute(
        "SELECT * FROM paper_reference WHERE paper_id=?", (paper["id"],)).fetchall()}
    old_by_ident = {(r["arxiv"] or r["doi"]): r for r in old.values() if r["arxiv"] or r["doi"]}
    con.execute("DELETE FROM paper_reference WHERE paper_id=?", (paper["id"],))
    for e in entries:
        m = _ARXIV_RE.search(e["raw"])
        e["arxiv"] = m.group(1) if m and "arxiv" in e["raw"].lower() else None
        m = _DOI_RE.search(e["raw"])
        e["doi"] = m.group(1).rstrip(".,;") if m else None
        fp = _fingerprint(e["raw"])
        prev = old.get(fp) or old_by_ident.get(e["arxiv"] or e["doi"])
        con.execute(
            "INSERT INTO paper_reference (paper_id, num, raw, arxiv, doi, ref_start, "
            "ref_end, matched_paper_id, verdict, verdict_comment, fingerprint, created) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (paper["id"], e["num"], e["raw"][:800], e["arxiv"], e["doi"],
             e["start"], e["end"], _match_paper(con, e),
             prev["verdict"] if prev else None,
             prev["verdict_comment"] if prev else None, fp, now()))
    con.commit()
    return {"key": key, "section_start": sec, "count": len(entries),
            "style": "numeric" if entries else "unknown"}


def _derive_status(r: dict) -> str:
    if r["verdict"] == "not_relevant":
        return "not_relevant"
    return "library" if r["matched_paper_id"] else "unknown"


def list_references(con: sqlite3.Connection, key: str) -> list[dict]:
    rows = [row_to_dict(r) for r in con.execute(
        "SELECT pr.*, p.key AS matched_key, p.title AS matched_title, "
        "p.authors_json AS matched_authors, p.year AS matched_year, "
        "p.inbox AS matched_inbox FROM paper_reference pr "
        "LEFT JOIN paper p ON p.id = pr.matched_paper_id "
        "JOIN paper cp ON cp.id = pr.paper_id WHERE cp.key=? ORDER BY pr.num",
        (key,)).fetchall()]
    for r in rows:
        r["status"] = _derive_status(r)
    return rows


def reference_markers(con: sqlite3.Connection, root, key: str, *, parser: str = "auto") -> dict:
    """The in-text citation markers + per-number status, for viewer decoration."""
    from .parse import parse
    refs = list_references(con, key)
    path = _library_file(Path(root), key)
    if path is None:
        raise ValueError(f"paper {key!r} has no full text in library/")
    text = parse(path, parser).text
    sec = _find_references_section(text)
    by_num = {r["num"]: r for r in refs}
    markers = find_markers(text, set(by_num), until=sec)
    for m in markers:
        m["status"] = min((by_num[n]["status"] for n in m["nums"]),
                          key=["not_relevant", "unknown", "library"].index)
    return {"markers": markers, "section_start": sec,
            "statuses": {n: by_num[n]["status"] for n in by_num}}


def mark_reference(con: sqlite3.Connection, ref_id: int, verdict: str | None,
                   comment: str | None = None) -> dict:
    """Record the human's relevance verdict on a cited reference.

    `verdict='not_relevant'` REQUIRES a comment — a dismissal without a why is
    exactly the unexplained dead end the log exists to prevent. `verdict=None`
    clears the mark.
    """
    if verdict not in (None, "not_relevant"):
        raise ValueError(f"verdict must be 'not_relevant' or None, got {verdict!r}")
    if verdict == "not_relevant" and not (comment or "").strip():
        raise ValueError("a not_relevant verdict requires a comment (the why)")
    r = con.execute("SELECT * FROM paper_reference WHERE id=?", (ref_id,)).fetchone()
    if not r:
        raise KeyError(f"no reference #{ref_id}")
    con.execute("UPDATE paper_reference SET verdict=?, verdict_comment=? WHERE id=?",
                (verdict, comment if verdict else None, ref_id))
    con.commit()
    out = row_to_dict(con.execute(
        "SELECT * FROM paper_reference WHERE id=?", (ref_id,)).fetchone())
    out["status"] = _derive_status(out)
    return out


def add_reference(con: sqlite3.Connection, root, ref_id: int, *,
                  download: bool = True, get=_http_get) -> dict:
    """Ingest a cited reference into the library (inbox'd as human-unread).

    Needs an explicit identifier on the entry (arXiv id or DOI) — guessing a
    paper from free text is how wrong papers enter a corpus.
    """
    r = con.execute("SELECT * FROM paper_reference WHERE id=?", (ref_id,)).fetchone()
    if not r:
        raise KeyError(f"no reference #{ref_id}")
    if r["matched_paper_id"]:
        raise ValueError(f"reference #{ref_id} is already in the library")
    source = r["arxiv"] or r["doi"]
    if not source:
        raise ValueError(
            f"reference #{ref_id} carries no arXiv id or DOI — resolve it manually "
            "(`renv discover \"<title>\"` then `renv add`), then rebuild references")
    res = ingest_add(con, root, source, download=download and bool(r["arxiv"]), get=get)
    con.execute("UPDATE paper SET inbox=1 WHERE id=?", (res["paper"]["id"],))
    con.execute("UPDATE paper_reference SET matched_paper_id=? WHERE id=?",
                (res["paper"]["id"], ref_id))
    con.commit()
    res["paper"] = row_to_dict(con.execute(
        "SELECT * FROM paper WHERE id=?", (res["paper"]["id"],)).fetchone())
    return res


def inbox(con: sqlite3.Connection) -> list[dict]:
    """Papers added to the corpus that no human has read yet."""
    return [row_to_dict(r) for r in con.execute(
        "SELECT * FROM paper WHERE inbox=1 AND read_at IS NULL ORDER BY added").fetchall()]


def mark_read(con: sqlite3.Connection, key: str) -> dict:
    r = con.execute("SELECT id FROM paper WHERE key=?", (key,)).fetchone()
    if not r:
        raise KeyError(f"no paper {key!r}")
    con.execute("UPDATE paper SET read_at=?, inbox=0 WHERE id=?", (now(), r["id"]))
    con.commit()
    return row_to_dict(con.execute("SELECT * FROM paper WHERE id=?", (r["id"],)).fetchone())
