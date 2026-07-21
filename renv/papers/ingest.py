"""Ingest external papers into the library + `paper` table (Pillar 1).

`renv add` turns a PDF / arXiv id / DOI into a first-class, identified entry: it
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

from renv.config import sha256_file
from renv.research.db import now, project_id, row_to_dict

ARXIV_API = "https://export.arxiv.org/api/query?id_list={}"
ARXIV_SEARCH = "https://export.arxiv.org/api/query?search_query={}&start=0&max_results={}"
ARXIV_PDF = "https://arxiv.org/pdf/{}.pdf"
CROSSREF_API = "https://api.crossref.org/works/{}"
_ATOM = "{http://www.w3.org/2005/Atom}"

_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
_STOP = {"the", "and", "for", "with", "from", "into", "their", "using", "via",
         "are", "can", "that", "this", "towards", "toward", "based", "generation"}


def _http_get(url: str, *, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "renv/0.1 (research-env)"})
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


def search_arxiv(query: str, *, max_results: int = 10, get=_http_get,
                 field: str = "auto") -> list[dict]:
    """Discover relevant papers on arXiv. Metadata only.

    ``field='auto'`` (default) queries the title field first with the query as a
    quoted phrase — exact paper titles then rank first instead of drowning in the
    API's OR-matched ``all:`` results — and falls back to ``all:`` when the title
    search comes up empty. ``field='ti'``/``'all'`` force one mode.
    """
    def _run(search_query: str) -> list[dict]:
        root = _safe_xml(get(ARXIV_SEARCH.format(urllib.parse.quote(search_query), max_results)))
        return [_parse_arxiv_entry(e) for e in root.findall(f"{_ATOM}entry")
                if e.findtext(f"{_ATOM}title")]

    if field not in ("auto", "ti", "all"):
        raise ValueError(f"field must be auto|ti|all, got {field!r}")
    if field in ("auto", "ti"):
        hits = _run(f'ti:"{query}"')
        if hits or field == "ti":
            return hits
    return _run(f"all:{query}")


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


def _meta_from_row(row) -> dict:
    """Rebuild the metadata dict from a stored paper row (used to preserve known
    metadata when attaching a file to an existing key)."""
    return {"title": row["title"], "authors": json.loads(row["authors_json"] or "[]"),
            "year": row["year"], "venue": row["venue"], "doi": row["doi"],
            "arxiv": row["arxiv"], "url": row["url"]}


def add(con: sqlite3.Connection, root, source: str, *,
        key=None, download=False, get=_http_get, meta_override=None) -> dict:
    """Ingest a source: fetch/derive metadata, land any file in library/, upsert paper.

    Identity invariant: a landed file is always named ``<key>.<ext>`` so the
    index's source_id (the file stem) equals the paper key and citations resolve
    to their paper row. Ingesting a file whose key already exists ATTACHES the
    full text to that paper (its stored metadata is preserved, not clobbered by
    the filename stub). ``meta_override`` (title/authors/year/...) fills the gaps
    local files can't self-describe.
    """
    kind, ident = detect(source)
    library = Path(root) / "library"
    library.mkdir(parents=True, exist_ok=True)
    sha = None
    landed = None
    attached = False

    if kind == "file":
        src = Path(ident)
        key = key or src.stem
        dest = library / f"{key}{src.suffix.lower()}"
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        sha, landed = sha256_file(dest), dest
        existing = con.execute("SELECT * FROM paper WHERE key=?", (key,)).fetchone()
        if existing:
            meta = _meta_from_row(existing)
            attached = True
        else:
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

    if meta_override:
        meta.update({k: v for k, v in meta_override.items() if v is not None})
    paper = add_paper(con, meta, sha256=sha, key=key)
    has_text = landed is not None or _library_file(Path(root), paper["key"]) is not None
    return {"paper": paper, "kind": kind,
            "landed": str(landed) if landed else None,
            "attached": attached, "has_text": has_text,
            "reindex": landed is not None}


def _library_file(root: Path, stem: str) -> Path | None:
    """The library file whose stem is `stem`, if any (pdf/txt/md)."""
    for ext in (".pdf", ".txt", ".md"):
        p = root / "library" / f"{stem}{ext}"
        if p.exists():
            return p
    return None


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


def citations_for_project(con: sqlite3.Connection, project: str,
                          *, live_only: bool = True) -> list[dict]:
    pid = project_id(con, project)
    live = " AND retracted IS NULL" if live_only else ""
    return [row_to_dict(r) for r in con.execute(
        f"SELECT * FROM citation WHERE project_id=?{live} ORDER BY id", (pid,)).fetchall()]


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


def remove_citation(con: sqlite3.Connection, citation_id: int, *, force: bool = False,
                    reason: str | None = None) -> dict:
    """Retract a citation row (mis-anchored span, wrong source).

    The row is TOMBSTONED, not deleted — a physical DELETE would cascade into
    ``claim_evidence`` and erase evidence history the store promises to keep.
    A citation that is LIVE evidence on a claim is load-bearing: retraction is
    refused unless ``force``, which first retracts those evidence links and
    re-derives each claim's status. Returns {"id", "project",
    "retracted_evidence": [claim ids]} so the caller can regenerate the sidecar.
    """
    row = con.execute("SELECT * FROM citation WHERE id=?", (citation_id,)).fetchone()
    if not row:
        raise KeyError(f"no citation #{citation_id}")
    if row["retracted"]:
        raise ValueError(f"citation #{citation_id} is already retracted")
    live = con.execute(
        "SELECT id, claim_id FROM claim_evidence WHERE citation_id=? AND retracted IS NULL",
        (citation_id,)).fetchall()
    if live and not force:
        claims = ", ".join(f"#{r['claim_id']}" for r in live)
        raise ValueError(
            f"citation #{citation_id} is live evidence on claim(s) {claims} — "
            "retract there first, or pass force=True to retract both")
    retracted = []
    if live:
        from renv.research.claim import _recompute_status
        for r in live:
            con.execute(
                "UPDATE claim_evidence SET retracted=?, retract_reason=? WHERE id=?",
                (now(), f"citation #{citation_id} retracted", r["id"]))
            retracted.append(r["claim_id"])
        for cid in set(retracted):
            _recompute_status(con, cid)
    slug = con.execute("SELECT slug FROM project WHERE id=?", (row["project_id"],)).fetchone()
    con.execute("UPDATE citation SET retracted=?, retract_reason=? WHERE id=?",
                (now(), reason or "mis-anchored", citation_id))
    con.commit()
    return {"id": citation_id, "project": slug["slug"] if slug else None,
            "retracted_evidence": retracted}


def rename_source(con: sqlite3.Connection, root, old_source_id: str, key: str) -> dict:
    """Repair an identity split: rename library/<old>.<ext> to <key>.<ext> and
    repoint existing citations (source_id + paper_id) at the paper row for `key`.

    The vector index bakes source ids in, so the caller must re-run
    ``renv index`` afterwards; affected projects are returned for sidecar regen.
    """
    src = _library_file(Path(root), old_source_id)
    if src is None:
        raise KeyError(f"no library file with stem {old_source_id!r}")
    paper = con.execute("SELECT id FROM paper WHERE key=?", (key,)).fetchone()
    if not paper:
        raise KeyError(f"no paper with key {key!r} — `renv add` it first")
    dest = src.with_stem(key) if hasattr(src, "with_stem") else src.parent / f"{key}{src.suffix}"
    if dest.exists() and dest != src:
        raise ValueError(f"{dest} already exists")
    src.rename(dest)
    con.execute("UPDATE paper SET sha256=? WHERE key=?", (sha256_file(dest), key))
    con.execute("UPDATE citation SET source_id=?, paper_id=? WHERE source_id=?",
                (key, paper["id"], old_source_id))
    projects = [r["slug"] for r in con.execute(
        "SELECT DISTINCT p.slug FROM citation c JOIN project p ON p.id=c.project_id "
        "WHERE c.source_id=?", (key,)).fetchall()]
    con.commit()
    return {"file": str(dest), "projects": projects, "reindex": True}


# --- BibTeX import -----------------------------------------------------------
_BIB_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)
_BIB_SKIP_TYPES = {"comment", "string", "preamble"}


def _bib_fields(body: str) -> dict:
    """Parse `name = {...}|"..."|bare` fields from an entry body (brace-aware)."""
    fields, i, n = {}, 0, len(body)
    while i < n:
        m = re.compile(r"\s*(\w+)\s*=\s*").match(body, i)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        if i < n and body[i] == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += {"{": 1, "}": -1}.get(body[j], 0)
                j += 1
            fields[name], i = body[i + 1:j - 1], j
        elif i < n and body[i] == '"':
            j = body.find('"', i + 1)
            j = n if j < 0 else j
            fields[name], i = body[i + 1:j], j + 1
        else:
            m2 = re.compile(r"[^,\s}]+").match(body, i)
            if m2:
                fields[name], i = m2.group(0), m2.end()
        i = body.find(",", i) + 1 or n
    return {k: " ".join(v.split()) for k, v in fields.items()}


def parse_bibtex(text: str) -> list[dict]:
    """Parse BibTeX entries to [{'bibkey', 'type', 'fields'}] (stdlib, tolerant)."""
    entries = []
    for m in _BIB_ENTRY_RE.finditer(text):
        etype = m.group(1).lower()
        if etype in _BIB_SKIP_TYPES:
            continue
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        entries.append({"bibkey": m.group(2), "type": etype,
                        "fields": _bib_fields(text[m.end():i - 1])})
    return entries


def resolve_bib_entry(fields: dict) -> tuple[str, str] | None:
    """Map a bib entry to an ingestable source: ('arxiv', id) or ('doi', doi)."""
    hay = " ".join(fields.get(k, "") for k in
                   ("eprint", "journal", "note", "howpublished", "url", "volume"))
    if "arxiv" in hay.lower() or fields.get("archiveprefix", "").lower() == "arxiv":
        m = _ARXIV_RE.search(fields.get("eprint", "") or hay)
        if m:
            return "arxiv", m.group(1)
    if fields.get("doi"):
        m = _DOI_RE.search(fields["doi"])
        if m:
            return "doi", m.group(1)
    return None


def add_bib(con: sqlite3.Connection, root, path, *,
            download=False, get=_http_get) -> dict:
    """Ingest every resolvable entry of a .bib file, keyed by its bib key.

    Entries resolve via an explicit arXiv id or DOI only — a wrong auto-matched
    paper is worse than an honest 'unresolved', so title search is left to
    `renv discover`. Returns {'added': [...], 'unresolved': [...], 'failed': [...]}.
    """
    entries = parse_bibtex(Path(path).read_text(errors="replace"))
    added, unresolved, failed = [], [], []
    for e in entries:
        res = resolve_bib_entry(e["fields"])
        if res is None:
            unresolved.append({"bibkey": e["bibkey"],
                               "title": e["fields"].get("title", "")})
            continue
        kind, ident = res
        try:
            r = add(con, root, ident, key=e["bibkey"], download=download, get=get)
            added.append({"bibkey": e["bibkey"], "kind": kind,
                          "landed": r["landed"], "has_text": r["has_text"]})
        except Exception as exc:  # keep going: one bad entry must not stop the batch
            failed.append({"bibkey": e["bibkey"], "source": ident, "error": str(exc)})
    return {"added": added, "unresolved": unresolved, "failed": failed}


def paper_usage(con: sqlite3.Connection, key: str) -> dict:
    """The reverse index: where a paper is cited, and which log entries use it."""
    paper = con.execute("SELECT * FROM paper WHERE key=?", (key,)).fetchone()
    cites = con.execute(
        "SELECT c.id, p.slug AS project, c.manuscript_loc, c.support, c.quote "
        "FROM citation c JOIN project p ON p.id=c.project_id "
        "WHERE c.paper_id=(SELECT id FROM paper WHERE key=?) "
        "AND c.retracted IS NULL ORDER BY c.id", (key,)
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
