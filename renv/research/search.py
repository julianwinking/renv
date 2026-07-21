"""Knowledge-base search across the store — papers, cards, notes, log, claims.

Uses SQLite FTS5 when available (most builds have it), falling back to a LIKE
scan otherwise. The index is built fresh per query from the current rows (a temp
FTS table), so results are always consistent with the store and there are no
triggers to keep in sync — fine at personal-corpus scale.
"""

from __future__ import annotations

import sqlite3


def _collect(con: sqlite3.Connection, project: str | None) -> list[tuple]:
    items: list[tuple] = []
    # papers + cards are global
    for r in con.execute("SELECT key, title, venue FROM paper").fetchall():
        items.append(("paper", r["key"], None, r["title"] or r["key"],
                      " ".join(x for x in (r["title"], r["venue"], r["key"]) if x)))
    for r in con.execute(
            "SELECT c.id, c.field, c.text, p.key FROM card c JOIN paper p ON p.id=c.paper_id").fetchall():
        items.append(("card", f"{r['key']}/{r['field']}", None, f"{r['key']} · {r['field']}", r["text"] or ""))
    # project-scoped prose
    slugs = ([project] if project else
             [r["slug"] for r in con.execute("SELECT slug FROM project").fetchall()])
    for slug in slugs:
        prow = con.execute("SELECT id FROM project WHERE slug=?", (slug,)).fetchone()
        if not prow:
            continue
        pid = prow["id"]
        for r in con.execute("SELECT id, title, body_md FROM note WHERE project_id=?", (pid,)).fetchall():
            items.append(("note", r["id"], slug, r["title"] or "note", r["body_md"]))
        for r in con.execute("SELECT id, type, body_md FROM log_entry WHERE project_id=?", (pid,)).fetchall():
            items.append(("log", r["id"], slug, r["type"], r["body_md"]))
        for r in con.execute("SELECT id, kind, text FROM claim WHERE project_id=?", (pid,)).fetchall():
            items.append(("claim", r["id"], slug, r["kind"], r["text"]))
    return items


def _has_fts5(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x)")
        con.execute("DROP TABLE temp.__fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def _fts_query(query: str) -> str:
    # AND of quoted terms — robust against FTS5 operator characters in user input
    terms = [t for t in query.replace('"', " ").split() if t]
    return " ".join(f'"{t}"' for t in terms) or '""'


def search(con: sqlite3.Connection, query: str, *, project: str | None = None,
           limit: int = 30) -> list[dict]:
    items = _collect(con, project)
    if not query.strip():
        return []
    if _has_fts5(con):
        con.execute("CREATE VIRTUAL TABLE temp.kb USING fts5(kind, ref, project, title, body)")
        try:
            con.executemany(
                "INSERT INTO temp.kb VALUES (?,?,?,?,?)",
                [(k, str(r), p or "", t or "", b or "") for k, r, p, t, b in items])
            rows = con.execute(
                "SELECT kind, ref, project, title, "
                "snippet(kb, 4, '[', ']', '…', 10) AS snippet "
                "FROM temp.kb WHERE kb MATCH ? ORDER BY rank LIMIT ?",
                (_fts_query(query), limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.execute("DROP TABLE temp.kb")
    # LIKE fallback
    terms = query.lower().split()
    out = []
    for k, r, p, t, b in items:
        hay = f"{t} {b}".lower()
        if all(term in hay for term in terms):
            out.append({"kind": k, "ref": str(r), "project": p or "",
                        "title": t, "snippet": (b or "")[:120]})
    return out[:limit]
