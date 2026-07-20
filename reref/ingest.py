"""Ingest external papers into the library + `paper` table (Pillar 1).

`reref add` turns a PDF / arXiv id / DOI into a first-class, identified entry: it
fetches bibliographic metadata (arXiv Atom API or Crossref REST API, both via
stdlib urllib), derives a stable key, and upserts a `paper` row — so the citation
usage map, `weave_bib`, and structured extraction all have real data to work with.

The HTTP layer is a single injectable function (`get=`), so the metadata parsers
are unit-tested against canned responses with no network.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

from .config import sha256_file
from .db import now, project_id, row_to_dict

ARXIV_API = "https://export.arxiv.org/api/query?id_list={}"
ARXIV_SEARCH = "https://export.arxiv.org/api/query?search_query=all:{}&start=0&max_results={}"
ARXIV_PDF = "https://arxiv.org/pdf/{}.pdf"
CROSSREF_API = "https://api.crossref.org/works/{}"
_ATOM = "{http://www.w3.org/2005/Atom}"

_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
_STOP = {"the", "and", "for", "with", "from", "into", "their", "using", "via",
         "are", "can", "that", "this", "towards", "toward", "based", "generation"}


def _http_get(url: str, *, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "reref/0.1 (research-env)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# --- source classification ---------------------------------------------------
def detect(source: str) -> tuple[str, str]:
    """Classify a source string as ('file'|'arxiv'|'doi', identifier)."""
    s = source.strip()
    p = Path(s)
    if p.exists() and p.suffix.lower() in {".pdf", ".txt", ".md"}:
        return "file", str(p)
    low = s.lower()
    m = _ARXIV_RE.search(s)
    if m and ("arxiv" in low or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", s)):
        return "arxiv", m.group(1)
    m = _DOI_RE.search(s)
    if m:
        return "doi", m.group(1)
    raise ValueError(f"could not classify {source!r} — expected a file path, arXiv id, or DOI")


# --- metadata fetchers (network injected via `get`) --------------------------
def _safe_xml(data: bytes) -> ET.Element:
    """Parse XML, refusing DTD/entity declarations (billion-laughs / XXE guard)."""
    head = data[:2048].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("refusing XML with a DTD/entity declaration")
    return ET.fromstring(data)


def _parse_arxiv_entry(entry) -> dict:
    published = entry.findtext(f"{_ATOM}published") or ""
    eid = entry.findtext(f"{_ATOM}id") or ""
    aid = eid.rsplit("/abs/", 1)[-1] if "/abs/" in eid else None
    return {
        "title": " ".join((entry.findtext(f"{_ATOM}title") or "").split()),
        "authors": [(a.findtext(f"{_ATOM}name") or "").strip()
                    for a in entry.findall(f"{_ATOM}author")
                    if (a.findtext(f"{_ATOM}name") or "").strip()],
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "arxiv": aid, "doi": None, "venue": None, "url": eid,
        "abstract": " ".join((entry.findtext(f"{_ATOM}summary") or "").split()),
    }


def fetch_arxiv(arxiv_id: str, *, get=_http_get) -> dict:
    root = _safe_xml(get(ARXIV_API.format(arxiv_id)))
    entry = root.find(f"{_ATOM}entry")
    if entry is None or entry.findtext(f"{_ATOM}title") is None:
        raise LookupError(f"arXiv {arxiv_id} not found")
    meta = _parse_arxiv_entry(entry)
    meta["arxiv"] = arxiv_id
    meta["url"] = f"https://arxiv.org/abs/{arxiv_id}"
    return meta


def search_arxiv(query: str, *, max_results: int = 10, get=_http_get) -> list[dict]:
    """Discover relevant papers by keyword (arXiv full-text). Metadata only."""
    root = _safe_xml(get(ARXIV_SEARCH.format(urllib.parse.quote(query), max_results)))
    return [_parse_arxiv_entry(e) for e in root.findall(f"{_ATOM}entry")
            if e.findtext(f"{_ATOM}title")]


def fetch_crossref(doi: str, *, get=_http_get) -> dict:
    msg = json.loads(get(CROSSREF_API.format(urllib.parse.quote(doi))))["message"]
    parts = (msg.get("published") or msg.get("issued") or {}).get("date-parts", [[None]])
    return {
        "title": (msg.get("title") or [""])[0],
        "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in msg.get("author", [])],
        "year": parts[0][0] if parts and parts[0] else None,
        "doi": msg.get("DOI"), "arxiv": None,
        "venue": (msg.get("container-title") or [None])[0],
        "url": msg.get("URL"), "abstract": msg.get("abstract"),
    }


def derive_key(meta: dict) -> str:
    authors = meta.get("authors") or []
    surname = authors[0].split()[-1] if authors and authors[0] else "anon"
    year = meta.get("year") or ""
    title = meta.get("title") or ""
    word = next((w for w in re.findall(r"[A-Za-z]+", title)
                 if len(w) > 3 and w.lower() not in _STOP), "paper")
    return re.sub(r"[^a-z0-9_]", "", f"{surname}{year}_{word}".lower())


# --- the paper table ---------------------------------------------------------
def add_paper(con: sqlite3.Connection, meta: dict, *, sha256=None, key=None) -> dict:
    """Upsert a paper row (by unique key); returns the stored row."""
    key = key or derive_key(meta)
    con.execute(
        "INSERT INTO paper (key, title, authors_json, year, venue, doi, arxiv, url, "
        "sha256, tags_json, added) VALUES (:key,:title,:authors,:year,:venue,:doi,"
        ":arxiv,:url,:sha256,:tags,:added) "
        "ON CONFLICT(key) DO UPDATE SET title=excluded.title, "
        "authors_json=excluded.authors_json, year=excluded.year, venue=excluded.venue, "
        "doi=excluded.doi, arxiv=excluded.arxiv, url=excluded.url, "
        "sha256=COALESCE(excluded.sha256, paper.sha256)",
        {"key": key, "title": meta.get("title"),
         "authors": json.dumps(meta.get("authors") or []),
         "year": meta.get("year"), "venue": meta.get("venue"), "doi": meta.get("doi"),
         "arxiv": meta.get("arxiv"), "url": meta.get("url"), "sha256": sha256,
         "tags": json.dumps(meta.get("tags") or []), "added": now()},
    )
    con.commit()
    return row_to_dict(con.execute("SELECT * FROM paper WHERE key=?", (key,)).fetchone())


def add(con: sqlite3.Connection, root, source: str, *,
        key=None, download=False, get=_http_get) -> dict:
    """Ingest a source: fetch/derive metadata, land any file in library/, upsert paper."""
    kind, ident = detect(source)
    library = Path(root) / "library"
    library.mkdir(parents=True, exist_ok=True)
    sha = None
    landed = None

    if kind == "file":
        src = Path(ident)
        key = key or src.stem
        dest = library / src.name
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        sha, landed = sha256_file(dest), dest
        meta = {"title": src.stem, "authors": [], "year": None}
    elif kind == "arxiv":
        meta = fetch_arxiv(ident, get=get)
        if download:
            key = key or derive_key(meta)
            dest = library / f"{key}.pdf"
            dest.write_bytes(get(ARXIV_PDF.format(ident)))
            sha, landed = sha256_file(dest), dest
    else:  # doi
        meta = fetch_crossref(ident, get=get)

    paper = add_paper(con, meta, sha256=sha, key=key)
    return {"paper": paper, "kind": kind,
            "landed": str(landed) if landed else None,
            "reindex": landed is not None}


def list_papers(con: sqlite3.Connection) -> list[dict]:
    return [row_to_dict(r) for r in
            con.execute("SELECT * FROM paper ORDER BY key").fetchall()]


# --- Pillar 3 ↔ store: record a citation row + the usage map -----------------
def record_citation(con: sqlite3.Connection, project: str, cit,
                    *, manuscript_loc: str | None = None) -> dict:
    """Persist an emitted citation as a row (links to a paper if its key matches)."""
    pid = project_id(con, project)
    paper = con.execute("SELECT id FROM paper WHERE key=?", (cit.source_id,)).fetchone()
    cur = con.execute(
        "INSERT INTO citation (project_id, paper_id, source_id, claim_text, src_start, "
        "src_end, quote, prefix, suffix, support, support_score, manuscript_loc, created) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, paper["id"] if paper else None, cit.source_id, cit.claim, cit.start, cit.end,
         cit.quote, cit.prefix, cit.suffix, cit.support, cit.support_score,
         manuscript_loc, now()),
    )
    con.commit()
    return row_to_dict(con.execute("SELECT * FROM citation WHERE id=?", (cur.lastrowid,)).fetchone())


def citations_for_project(con: sqlite3.Connection, project: str) -> list[dict]:
    pid = project_id(con, project)
    return [row_to_dict(r) for r in con.execute(
        "SELECT * FROM citation WHERE project_id=? ORDER BY id", (pid,)).fetchall()]


def regenerate_sidecar(con: sqlite3.Connection, project: str, project_root) -> "Path":
    """Write citations.json as a DERIVED view of the citation table (single truth)."""
    rows = citations_for_project(con, project)
    data = [{"claim": r["claim_text"], "source_id": r["source_id"],
             "start": r["src_start"], "end": r["src_end"], "quote": r["quote"],
             "prefix": r["prefix"], "suffix": r["suffix"], "support": r["support"],
             "support_score": r["support_score"], "manuscript_loc": r["manuscript_loc"]}
            for r in rows]
    out = Path(project_root) / "citations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))
    return out


def paper_usage(con: sqlite3.Connection, key: str) -> dict:
    """The reverse index: where a paper is cited, and which log entries use it."""
    paper = con.execute("SELECT * FROM paper WHERE key=?", (key,)).fetchone()
    cites = con.execute(
        "SELECT c.id, p.slug AS project, c.manuscript_loc, c.support, c.quote "
        "FROM citation c JOIN project p ON p.id=c.project_id "
        "WHERE c.paper_id=(SELECT id FROM paper WHERE key=?) ORDER BY c.id", (key,)
    ).fetchall()
    cite_ids = [c["id"] for c in cites]
    used_in = []
    if cite_ids:
        marks = ",".join("?" * len(cite_ids))
        used_in = [row_to_dict(r) for r in con.execute(
            f"SELECT le.id, le.type, le.experiment_id FROM log_entry le "
            f"JOIN log_evidence ev ON ev.log_entry_id=le.id "
            f"WHERE ev.citation_id IN ({marks})", cite_ids).fetchall()]
    return {"paper": row_to_dict(paper),
            "cited_in": [row_to_dict(c) for c in cites],
            "used_in_log": used_in}
