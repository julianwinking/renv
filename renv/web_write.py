"""Cockpit manuscript routes — thin shell over ``renv.research.manuscript``.

A new route surface lives in its own module (AGENTS.md #10). web.py's dispatch
table points here; every write still goes through the domain.
"""

from __future__ import annotations

from pathlib import Path

from renv.research import authoring, manuscript


def get_tree(h, con, q, slug):
    return manuscript.list_tree(con, h.root, slug)


def get_file(h, con, q, slug):
    rel = (q.get("path") or [""])[0]
    return manuscript.read_file(con, h.root, slug, rel)


def get_context(h, con, q, slug):
    return manuscript.writing_context(con, h.root, slug)


def get_synctex(h, con, q, slug):
    """tex→PDF (dir=tex) or PDF→tex (dir=pdf). Honest JSON when SyncTeX is missing."""
    from renv.research.db import project_id
    project_id(con, slug)
    text = Path(h.root) / "projects" / slug / "text"
    direction = (q.get("dir") or ["tex"])[0]
    main = (q.get("main") or ["paper.tex"])[0] or "paper.tex"
    if direction == "pdf":
        page = int(float((q.get("page") or ["1"])[0] or 1))
        x = float((q.get("x") or ["0"])[0] or 0)
        y = float((q.get("y") or ["0"])[0] or 0)
        snippet = (q.get("snippet") or [None])[0] or None
        prefer = (q.get("prefer") or [None])[0] or None
        return manuscript.sync_from_pdf(
            text, page, x, y, snippet=snippet, prefer=prefer, main=main)
    rel = (q.get("path") or ["paper.tex"])[0] or "paper.tex"
    line = int(float((q.get("line") or ["1"])[0] or 1))
    body = (q.get("text") or [None])[0] or None
    return manuscript.sync_from_tex(text, rel, line, text=body, main=main)


def serve_pdf(handler, slug):
    """Binary PDF — called from do_GET, not the JSON dispatcher."""
    from renv.research import db
    con = db.connect(handler.root)
    try:
        data = manuscript.pdf_bytes(con, handler.root, slug)
    except (KeyError, ValueError) as exc:
        return handler._send({"error": f"{type(exc).__name__}: {exc}"}, 404,
                             cache="no-store")
    finally:
        con.close()
    return handler._send(data, ctype="application/pdf", cache="no-store")


def post_file(h, con, d, slug):
    return manuscript.write_file(con, h.root, slug, d["path"], d.get("content", ""))


def post_delete(h, con, d, slug):
    return manuscript.delete_file(con, h.root, slug, d["path"])


def post_weave(h, con, d, slug):
    paths = authoring.weave(con, slug, Path(h.root) / "projects" / slug)
    return {"generated": [p.name for p in paths]}


def post_compile(h, con, d, slug):
    return manuscript.compile_manuscript(
        con, h.root, slug,
        main=d.get("main") or "paper.tex",
        weave=bool(d.get("weave", True)))


def post_cite(h, con, d, slug):
    try:
        return manuscript.cite_claim(
            con, h.root, d.get("claim", ""),
            project=slug, source=d.get("source"), write=bool(d.get("write")),
            force=bool(d.get("force")), verifier=d.get("verifier") or "lexical",
            top_k=int(d.get("top_k") or 5),
            manuscript_loc=d.get("manuscript_loc"),
            pick=int(d.get("pick") or 0))
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
