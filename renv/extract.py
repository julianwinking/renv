"""Structured per-paper extraction → `card` rows (Pillar 2).

A card distills a paper into machine-readable fields (problem, method,
contributions, results, limitations), each anchored to a source span so the card
is itself citable and never becomes an unsourced second copy of the paper. The
default backend is a deterministic cue-phrase heuristic over the parsed sentences
(stdlib, free); a schema-constrained LLM backend is the documented `--extra api`
upgrade. Either way fields are anchored through the same offsets the engine uses.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import chunk, parse
from .db import now, row_to_dict

FIELDS = ["problem", "method", "contributions", "results", "limitations"]
_CUES = {
    "problem": ["problem", "challenge", "limitation", "hallucinat", "unsolved",
                "difficult", "fail", "lack", "gap"],
    "method": ["we propose", "we introduce", "we present", "we develop", "method",
               "approach", "benchmark", "framework", "we build", "we design"],
    "contributions": ["contribution", "we make", "we propose", "novel", "first to",
                      "we show", "we demonstrate"],
    "results": ["result", "accuracy", "outperform", "achiev", "improv", "score",
                "f1", "precision", "recall", "state-of-the-art", "%"],
    "limitations": ["limitation", "however", "future work", "caveat", "does not",
                    "cannot", "remains", "open problem"],
}


def source_path(root, key: str) -> Path | None:
    library = Path(root) / "library"
    for ext in (".txt", ".md", ".pdf"):
        p = library / f"{key}{ext}"
        if p.exists():
            return p
    return next(iter(sorted(library.glob(f"{key}.*"))), None)


def _paper_id(con: sqlite3.Connection, key: str) -> int:
    row = con.execute("SELECT id FROM paper WHERE key=?", (key,)).fetchone()
    if not row:
        raise KeyError(f"no paper {key!r} — `renv add` it first")
    return row["id"]


def _best_chunk_scored(chunks, cues):
    best, best_score = None, 0
    for c in chunks:
        low = c.text.lower()
        score = sum(1 for cue in cues if cue in low)
        if score > best_score:
            best, best_score = c, score
    return best, best_score


def extract_card(con: sqlite3.Connection, root, key: str, *, min_score: int = 2) -> dict:
    """(Re)generate the heuristic card for a paper; replaces any prior card rows.

    Heuristic and lossy: a field is emitted only when at least ``min_score`` distinct
    cue phrases match, so weak/ambiguous fields are left absent rather than filled
    with a confidently-wrong sentence. Every field records ``extracted_by`` and its
    score; consumers must treat heuristic cards as low-confidence, not ground truth.
    """
    pid = _paper_id(con, key)
    src = source_path(root, key)
    if not src:
        raise FileNotFoundError(f"no source file for {key!r} in library/")
    doc = parse.parse(src)
    chunks = chunk.chunk_text(key, doc.text)

    con.execute("DELETE FROM card WHERE paper_id=?", (pid,))
    card = {}
    for field in FIELDS:
        best, score = _best_chunk_scored(chunks, _CUES[field])
        if not best or score < min_score:
            continue
        anchor = {"start": best.start, "end": best.end, "quote": best.text, "score": score}
        con.execute(
            "INSERT INTO card (paper_id, field, text, anchor_json, extracted_by, generated) "
            "VALUES (?,?,?,?, 'heuristic', ?)",
            (pid, field, best.text, json.dumps(anchor), now()),
        )
        card[field] = {"text": best.text, "anchor": anchor, "confidence": score}
    con.commit()
    return card


def get_card(con: sqlite3.Connection, key: str) -> dict:
    pid = _paper_id(con, key)
    rows = con.execute("SELECT * FROM card WHERE paper_id=? ORDER BY id", (pid,)).fetchall()
    return {r["field"]: {"text": r["text"], "anchor": json.loads(r["anchor_json"] or "{}"),
                         "extracted_by": r["extracted_by"]} for r in rows}


def extract_all(con: sqlite3.Connection, root) -> dict:
    out = {}
    for r in con.execute("SELECT key FROM paper ORDER BY key").fetchall():
        try:
            out[r["key"]] = extract_card(con, root, r["key"])
        except FileNotFoundError:
            out[r["key"]] = {"skipped": "no source file"}
    return out
