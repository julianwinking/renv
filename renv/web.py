"""The web cockpit — a minimal local dashboard over the single SQLite ground truth.

Pure stdlib ``http.server`` (no framework, no build step): the *human* interface
that mirrors what an agent does via MCP. Every write goes through the same domain
functions as the CLI, so the §0 constraints hold whoever acts, and the page and the
agent see identical live state. Binds to 127.0.0.1 only.

On-demand serving (macOS): ``renv web install`` registers a launchd
LaunchAgent with SOCKET ACTIVATION — launchd holds the listening socket at
near-zero cost, starts this server on the first browser request, and the
server exits itself after ``--idle-exit`` seconds without traffic; launchd
then re-arms the socket. Deliberately NOT Docker: this server must read/write
the repo working tree (instructions, scaffolding, git health), and a container
would add mounts and drift for zero isolation benefit on a localhost tool.
"""

from __future__ import annotations

import ctypes
import json
import re
import socket as socketmod
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

_LOCAL_ORIGIN = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")

from . import claim as claimmod
from . import db, experiment, ingest
from . import finding as findmod
from . import log as logmod

WEB_DIR = Path(__file__).parent / "web"
DIST = Path(__file__).parent.parent / "cockpit" / "dist"   # built React Flow app (if present)
_MIME = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
         ".html": "text/html", ".svg": "image/svg+xml", ".json": "application/json",
         ".map": "application/json", ".wasm": "application/wasm"}


def _graph(con, root, slug):
    """A unified node/edge graph for a project: experiment DAG + claims + findings +
    citations + papers + code references, ready for a graph UI (React Flow). Neutral
    shape; the client lays it out (dagre) and maps kinds to node components."""
    pid = db.project_id(con, slug)
    nodes, edges, seen = [], [], set()
    saved = {r["node_id"]: {"x": r["x"], "y": r["y"]} for r in con.execute(
        "SELECT node_id, x, y FROM graph_layout WHERE project_id=?", (pid,))}

    def node(nid, kind, label, data):
        if nid in seen:
            return
        seen.add(nid)
        nodes.append({"id": nid, "kind": kind, "label": label, "data": data,
                      "pos": saved.get(nid)})

    for e in experiment.list_experiments(con, slug):
        node(f"exp:{e['id']}", "experiment", e["slug"],
             {"title": e["title"], "status": e["status"], "metrics": e["metrics"],
              "hypothesis": e["hypothesis"]})
        if e["parent_id"]:
            edges.append({"source": f"exp:{e['parent_id']}", "target": f"exp:{e['id']}",
                          "kind": "parent", "etype": "parent", "eid": e["id"]})

    for c in con.execute(
            "SELECT c.id, c.paper_id, c.support, c.quote, p.key, p.title FROM citation c "
            "LEFT JOIN paper p ON p.id=c.paper_id WHERE c.project_id=?", (pid,)).fetchall():
        node(f"cite:{c['id']}", "citation", (c["key"] or "cite") + f"#{c['id']}",
             {"support": c["support"], "quote": c["quote"]})
        if c["paper_id"]:
            node(f"paper:{c['paper_id']}", "paper", c["key"], {"title": c["title"]})
            edges.append({"source": f"paper:{c['paper_id']}", "target": f"cite:{c['id']}", "kind": "cited"})

    # positional paper notes: the reader's marginalia joins the graph, anchored
    # to its paper (which is pulled in even if never cited), free to go on to
    # motivate an experiment or argue a claim via context links
    from . import paper_note as pnotemod
    for n_ in pnotemod.list_for_project(con, slug):
        node(f"paper:{n_['paper_id']}", "paper", n_["paper_key"], {"title": n_["paper_title"]})
        label = (n_["body_md"] or n_["quote"] or "").strip()[:48]
        node(f"pnote:{n_['id']}", "pnote", label,
             {"text": n_["body_md"], "quote": n_["quote"], "page": n_["page"],
              "color": n_["color"], "paper_key": n_["paper_key"],
              "note_kind": n_.get("kind", "note")})
        edges.append({"source": f"paper:{n_['paper_id']}",
                      "target": f"pnote:{n_['id']}", "kind": "annotates"})

    for c in claimmod.list_claims(con, slug):
        full = claimmod.get_claim(con, c["id"])
        node(f"claim:{c['id']}", "claim", c["text"][:48],
             {"kind": c["kind"], "status": c["status"], "text": c["text"]})
        for ev in full["evidence"]:
            if ev["retracted"]:            # history, not proof — claim detail shows it
                continue
            meta = {"etype": "evidence", "eid": ev["id"], "grade": ev["grade"],
                    "stale": ev["stale"], "preregistered": ev["preregistered"],
                    "run_id": ev["run_id"], "citation_id": ev["citation_id"]}
            if ev["run_id"]:
                r = con.execute("SELECT experiment_id FROM run WHERE id=?", (ev["run_id"],)).fetchone()
                if r:
                    edges.append({"source": f"exp:{r['experiment_id']}", "target": f"claim:{c['id']}",
                                  "kind": ev["stance"], "note": ev["note"], **meta})
            if ev["citation_id"]:
                edges.append({"source": f"cite:{ev['citation_id']}", "target": f"claim:{c['id']}",
                              "kind": ev["stance"], "note": ev["note"], **meta})
    # pre-registrations: experiment ⇢ claim it declared it will test
    for t in claimmod.list_tests(con, slug):
        if f"exp:{t['experiment_id']}" in seen and f"claim:{t['claim_id']}" in seen:
            edges.append({"source": f"exp:{t['experiment_id']}",
                          "target": f"claim:{t['claim_id']}", "kind": "tests",
                          "etype": "tests", "eid": t["id"]})
    for rel in claimmod.list_relations(con, slug):
        edges.append({"source": f"claim:{rel['claim_id']}",
                      "target": f"claim:{rel['related_id']}", "kind": rel["kind"],
                      "note": rel["note"], "etype": "relation", "eid": rel["id"]})

    # soft context links (feedback relates-to a claim, note about an experiment…)
    from . import links as linksmod

    for lk in linksmod.list_links(con, slug):
        edges.append({"source": linksmod.graph_node_id(lk["from_kind"], lk["from_id"]),
                      "target": linksmod.graph_node_id(lk["to_kind"], lk["to_id"]),
                      "kind": lk["relation"], "note": lk["note"], "context": True,
                      "etype": "context", "eid": lk["id"]})

    # thinking made visible: every reasoning entry (question / hypothesis /
    # feedback / decision / blocker / observation) joins the graph, wired to
    # the experiment it concerns and to the entries that answer it
    _NODE_TYPES = ("question", "hypothesis", "feedback", "decision", "blocker", "observation")
    thought_rows = con.execute(
        "SELECT * FROM log_entry WHERE project_id=? AND ("
        f"type IN ({','.join('?' * len(_NODE_TYPES))}) OR answers IS NOT NULL) "
        "ORDER BY id", (pid, *_NODE_TYPES)).fetchall()
    for e in thought_rows:
        answered = None
        if e["type"] == "question":
            a = con.execute("SELECT 1 FROM log_entry WHERE answers=?", (e["id"],)).fetchone()
            answered = bool(a)
        node(f"log:{e['id']}", e["type"] if e["type"] in _NODE_TYPES else "thought",
             f"#{e['id']}", {"text": e["body_md"], "type": e["type"],
                             "source": e["source"], "answered": answered})
    for e in thought_rows:
        if e["experiment_id"]:
            edges.append({"source": f"log:{e['id']}",
                          "target": f"exp:{e['experiment_id']}", "kind": "about"})
        if e["answers"] and f"log:{e['answers']}" in seen:
            edges.append({"source": f"log:{e['id']}",
                          "target": f"log:{e['answers']}", "kind": "answers"})

    # meeting notes anchor the timeline side of the graph
    for n_ in con.execute("SELECT * FROM note WHERE project_id=? ORDER BY id", (pid,)).fetchall():
        node(f"note:{n_['id']}", "note", n_["title"] or f"note #{n_['id']}",
             {"text": n_["body_md"], "ts": n_["ts"]})

    for f in findmod.list_findings(con, slug, status="open"):
        node(f"finding:{f['id']}", "finding", f["check_id"],
             {"severity": f["severity"], "issue": f["issue"], "status": f["status"]})
        for ev in con.execute("SELECT citation_id FROM finding_evidence WHERE finding_id=?", (f["id"],)).fetchall():
            if ev["citation_id"]:
                edges.append({"source": f"finding:{f['id']}", "target": f"cite:{ev['citation_id']}", "kind": "about"})

    _add_code_refs(con, root, pid, nodes, edges, seen, node)
    return {"slug": slug, "nodes": nodes, "edges": edges}


def _add_code_refs(con, root, pid, nodes, edges, seen, node):
    """Add @renv code tags that point at a node already in this graph (code↔store)."""
    from . import refs as refsmod
    paper_id = {r["key"]: r["id"] for r in con.execute("SELECT id, key FROM paper")}
    exp_id = {e["slug"]: e["id"] for e in con.execute(
        "SELECT id, slug FROM experiment WHERE project_id=?", (pid,))}

    def resolve(kind, ident):
        if kind == "finding" and f"finding:{ident}" in seen:
            return f"finding:{ident}"
        if kind == "claim" and f"claim:{ident}" in seen:
            return f"claim:{ident}"
        if kind == "paper" and f"paper:{paper_id.get(ident)}" in seen:
            return f"paper:{paper_id[ident]}"
        if kind == "experiment" and exp_id.get(ident) and f"exp:{exp_id[ident]}" in seen:
            return f"exp:{exp_id[ident]}"
        if kind == "run":
            r = con.execute("SELECT experiment_id FROM run WHERE id=?", (ident,)).fetchone()
            if r and f"exp:{r['experiment_id']}" in seen:
                return f"exp:{r['experiment_id']}"
        return None

    try:
        found = refsmod.scan(root)
    except Exception:
        return
    for ref in found:
        target = resolve(ref["kind"], ref["id"])
        if not target:
            continue
        cid = f"code:{ref['file']}:{ref['line']}"
        node(cid, "code", f"{ref['file']}:{ref['line']}",
             {"relation": ref["relation"], "text": ref["text"]})
        edges.append({"source": cid, "target": target, "kind": ref["relation"] or "ref"})


def _overview(con):
    projects = [dict(r) for r in con.execute(
        "SELECT slug, title, status, created FROM project ORDER BY slug")]
    counts = {t: con.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
              for t in ("paper", "experiment", "run", "citation", "claim", "finding", "note")}
    for p in projects:
        p["open_findings"] = con.execute(
            "SELECT COUNT(*) n FROM finding WHERE status='open' AND "
            "project_id=(SELECT id FROM project WHERE slug=?)", (p["slug"],)).fetchone()["n"]
    # the §0 ledger indicator: does every result entry trace to a run?
    violations = logmod.check_invariants(con)
    return {"projects": projects, "counts": counts,
            "invariants": {"clean": not violations, "violations": len(violations)}}


def _health(con, root, slug):
    """A few load-bearing project-health checks — deliberately NOT a metrics
    wall: §0 ledger, the project's git repo, and export freshness. Each row is
    actionable or it doesn't belong here."""
    import subprocess
    checks = []

    v = logmod.check_invariants(con)
    checks.append({"id": "ledger", "label": "§0 ledger",
                   "status": "ok" if not v else "bad",
                   "detail": "every result entry traces to a run" if not v
                   else f"{len(v)} violation(s) — run `renv log check`"})

    proot = Path(root) / "projects" / slug
    if not (proot / ".git").exists():
        checks.append({"id": "repo", "label": "GitHub repo", "status": "bad",
                       "detail": f"no git repo — `git init` in projects/{slug}"})
    else:
        dirty = remotes = ""
        try:
            dirty = subprocess.run(["git", "-C", str(proot), "status", "--porcelain"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
            remotes = subprocess.run(["git", "-C", str(proot), "remote", "-v"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            pass
        if not remotes:
            st, detail = "warn", "repo exists, no remote — `git remote add origin <url>`"
        elif dirty:
            st, detail = "warn", f"{len(dirty.splitlines())} uncommitted change(s)"
        else:
            st, detail = "ok", "clean, remote linked"
        checks.append({"id": "repo", "label": "GitHub repo", "status": st, "detail": detail})

    dbp, wal = Path(root) / ".research" / "env.db", Path(root) / ".research" / "env.db-wal"
    store_m = max((p.stat().st_mtime for p in (dbp, wal) if p.exists()), default=0)
    exports = list((Path(root) / ".research" / "export").glob("*.jsonl"))
    if not exports:
        checks.append({"id": "export", "label": "Committed snapshot", "status": "warn",
                       "detail": "no export yet — `renv export` writes the git-committed record"})
    else:
        exp_m = max(f.stat().st_mtime for f in exports)
        if exp_m + 5 >= store_m:
            checks.append({"id": "export", "label": "Committed snapshot", "status": "ok",
                           "detail": "export is current with the store"})
        else:
            age = int((store_m - exp_m) / 60)
            checks.append({"id": "export", "label": "Committed snapshot", "status": "warn",
                           "detail": f"store changed ~{max(age, 1)} min after last export — `renv export`"})

    # argument health: contradictions and broken foundations are real problems
    from . import argument
    arg = argument.analyze(con, slug)["summary"]
    if arg["contradictions"]:
        checks.append({"id": "argument", "label": "Argument", "status": "bad",
                       "detail": f"{arg['contradictions']} supported claim(s) contradict each other"})
    elif arg["broken_foundations"]:
        checks.append({"id": "argument", "label": "Argument", "status": "warn",
                       "detail": f"{arg['broken_foundations']} claim(s) rest on a refuted lemma"})
    else:
        checks.append({"id": "argument", "label": "Argument", "status": "ok",
                       "detail": "no contradictions; foundations sound"})

    order = {"bad": 0, "warn": 1, "ok": 2}
    return {"checks": checks,
            "status": min((c["status"] for c in checks), key=lambda s: order[s])}


def _runs(con, slug):
    """All runs of a project (newest first) with params, dataset, and metrics —
    the raw material for the cockpit's runs ledger."""
    pid = db.project_id(con, slug)
    runs = [dict(r) for r in con.execute(
        "SELECT r.id, r.status, r.started, r.finished, r.seed, r.git_sha, "
        "       r.dirty, r.provenance, r.entrypoint, r.remote, e.slug AS experiment, "
        "       c.params_json, d.slug AS dataset, d.location AS dataset_location "
        "FROM run r JOIN experiment e ON e.id = r.experiment_id "
        "LEFT JOIN config c ON c.id = r.config_id "
        "LEFT JOIN dataset d ON d.id = r.dataset_id "
        "WHERE e.project_id=? ORDER BY r.id DESC", (pid,))]
    for r in runs:
        r["params"] = json.loads(r.pop("params_json") or "{}")
        r["metrics"] = {m["name"]: m["value"] for m in con.execute(
            "SELECT name, value FROM metric WHERE run_id=?", (r["id"],))}
    return runs


def _project(con, slug):
    from . import regions as regionsmod
    pid = db.project_id(con, slug)
    notes = [dict(r) for r in con.execute(
        "SELECT * FROM note WHERE project_id=? ORDER BY id DESC", (pid,))]
    log = logmod.list_entries(con, slug, limit=100)
    experiments = experiment.list_experiments(con, slug)
    claims = claimmod.list_claims(con, slug)
    # which region each graph node sits in (log:/note:/exp:/claim:<id>)
    mem = regionsmod.membership(con, slug)
    for e in log:
        e["region"] = mem.get(f"log:{e['id']}")
    for n in notes:
        n["region"] = mem.get(f"note:{n['id']}")
    for x in experiments:
        x["region"] = mem.get(f"exp:{x['id']}")
    for c in claims:
        c["region"] = mem.get(f"claim:{c['id']}")
    return {
        "slug": slug,
        "experiments": experiments,
        "findings": findmod.list_findings(con, slug),
        "claims": claims,
        "log": log,
        "notes": notes,
    }


def _regions(con, slug):
    """Regions, each carrying the phases it overlaps — derived geometrically
    from the phase bands (no stored link; a region is 'in' the phases where
    it has surface)."""
    from . import phases as phasesmod
    from . import regions as regionsmod
    regs = regionsmod.list_regions(con, slug)
    bands = [p for p in phasesmod.list_phases(con, slug) if p["x0"] is not None]
    for r in regs:
        r["phases"] = [p["title"] for p in bands
                       if max(p["x0"], r["x"]) < min(p["x1"], r["x"] + r["w"])]
    return regs


def _papers(con, root):
    """The corpus for the library table: each row flagged with whether its PDF
    is on disk (so the cockpit knows which papers can open in the viewer), its
    note and citation counts, and a parsed authors list."""
    lib = Path(root) / "library"
    out = ingest.list_papers(con)
    for p in out:
        p["has_pdf"] = (lib / f"{p['key']}.pdf").exists()
        p["note_count"] = con.execute(
            "SELECT COUNT(*) FROM paper_note WHERE paper_id=?", (p["id"],)).fetchone()[0]
        p["cite_count"] = con.execute(
            "SELECT COUNT(*) FROM citation WHERE paper_id=?", (p["id"],)).fetchone()[0]
        p["doc_count"] = con.execute(
            "SELECT COUNT(*) FROM paper_doc WHERE paper_id=?", (p["id"],)).fetchone()[0]
        try:
            p["authors"] = json.loads(p.get("authors_json") or "[]")
        except Exception:
            p["authors"] = []
    return out


# parsed-doc cache so repeated viewer loads don't re-parse the PDF for page hints
_PAGE_CACHE: dict = {}


def _page_mapper(root, key):
    """Return offset→page(1-based) for a paper's PDF, or None if unparseable
    (e.g. pdfminer not installed). Cached by file mtime."""
    src = Path(root) / "library" / f"{key}.pdf"
    if not src.exists():
        return None
    try:
        mtime = src.stat().st_mtime
        cached = _PAGE_CACHE.get(key)
        if not cached or cached[0] != mtime:
            from . import parse as parsemod
            _PAGE_CACHE[key] = (mtime, parsemod.parse(src))
        return _PAGE_CACHE[key][1].page_of
    except Exception:
        return None


def _paper_anchors(con, root, key, project):
    """Everything the PDF viewer highlights: the project's citations of this
    paper and its positional notes, each carrying a text-quote anchor (and a
    page hint when the PDF could be parsed) for text-layer matching."""
    prow = con.execute("SELECT id FROM paper WHERE key=?", (key,)).fetchone()
    if not prow:
        raise KeyError(f"no paper {key!r}")
    pid = prow["id"]
    if project:
        proj = db.project_id(con, project)
        rows = con.execute("SELECT * FROM citation WHERE paper_id=? AND project_id=? "
                           "ORDER BY id", (pid, proj)).fetchall()
    else:
        rows = con.execute("SELECT * FROM citation WHERE paper_id=? ORDER BY id",
                           (pid,)).fetchall()
    page_of = _page_mapper(root, key)
    citations = [{
        "id": c["id"], "quote": c["quote"], "prefix": c["prefix"], "suffix": c["suffix"],
        "support": c["support"], "claim_text": c["claim_text"],
        "page": (page_of(c["src_start"]) if page_of and c["src_start"] is not None else None),
    } for c in rows]
    from . import paper_note
    return {"key": key, "citations": citations,
            "notes": paper_note.list_for_paper(con, key, project)}


def _plan(con, slug):
    """Plan items; each phase carries the region (if any) that stands for it."""
    from . import regions as regionsmod, plan as planmod
    items = planmod.list_items(con, slug)
    by_phase = {r["plan_item_id"]: {"id": r["id"], "label": r["label"], "color": r["color"]}
                for r in regionsmod.list_regions(con, slug) if r.get("plan_item_id")}
    for it in items:
        if it["kind"] == "phase":
            it["region"] = by_phase.get(it["id"])
    return items


# --- admin control surface: the files agents actually read -------------------
# STRICT allowlist. These are the real levers of the environment: AGENTS.md is
# what an agent loads at session start, templates/ is what every `renv new`
# scaffolds from. The cockpit can edit exactly these — never arbitrary paths,
# and never code (tool prompts live in code; their designed control point IS
# AGENTS.md, so that is what we expose).
_CONFIG_FILES = {
    "env": {
        "AGENTS.md": "The operating protocol — every agent reads this at session start.",
    },
    "template": {
        "AGENTS.md": "Per-project agent instructions scaffolded into every NEW project.",
        "text/paper.tex": "Paper skeleton — the section structure of every NEW paper.",
        "README.md": "Readme scaffolded into every NEW project.",
    },
    "writing": {
        "paper-structure.md": "How a research paper is built — what each section must accomplish.",
        "thesis-structure.md": "How a thesis argument is built and defended.",
        "style.md": "Reusable research sentences and argument constructions.",
    },
    "project": {
        "AGENTS.md": "THIS project's overrides only — protocol inherits from the env AGENTS.md.",
    },
}
_CONFIG_MAX_BYTES = 512 * 1024


def _config_path(root, con, scope, name, project=None) -> Path:
    if name not in (_CONFIG_FILES.get(scope) or {}):
        raise ValueError(f"not an editable file: {scope}/{name}")
    base = Path(root)
    if scope == "env":
        return base / name
    if scope == "template":
        return base / "templates" / "project" / name
    if scope == "writing":
        return base / "templates" / "writing" / name
    db.project_id(con, project)   # validates the slug exists — no path games
    return base / "projects" / project / name


def _config_listing(root, con, project=None):
    out = []
    for scope, names in _CONFIG_FILES.items():
        if scope == "project" and not project:
            continue
        for name, desc in names.items():
            p = _config_path(root, con, scope, name, project)
            out.append({"scope": scope, "name": name, "description": desc,
                        "project": project if scope == "project" else None,
                        "exists": p.exists(),
                        "size": p.stat().st_size if p.exists() else 0})
    return out


class Handler(BaseHTTPRequestHandler):
    root = "."
    last_activity = time.monotonic()

    def log_message(self, *a):  # keep the console quiet
        pass

    def handle_one_request(self):
        Handler.last_activity = time.monotonic()   # any traffic resets the idle clock
        super().handle_one_request()

    def _send(self, obj, status=200, ctype="application/json", cache=None):
        body = obj if isinstance(obj, (bytes, bytearray)) else json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", cache)
        # CORS: only trust local dev origins (Vite on :5173 etc.) — never `*`.
        # A wildcard would let any website the browser visits read/write the
        # research DB via drive-by fetch; same-origin requests need no header.
        origin = self.headers.get("Origin", "")
        if _LOCAL_ORIGIN.match(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # CORS preflight
        self._send(b"", 204, "text/plain")

    def _serve_app(self, path):
        """Serve the built React Flow app from cockpit/dist if present, else the
        simple buildless page. Clean-URL routing: real assets are served as-is,
        a missing asset stays a 404, and any other path (``/overview``,
        ``/papers/<key>``, …) returns the SPA shell so reloads and deep links
        resolve to the client router."""
        page = DIST / "index.html" if (DIST / "index.html").exists() else WEB_DIR / "index.html"

        def shell():
            # never cache the shell: it references hash-named bundles that change
            # on every rebuild — a cached shell shows a stale app
            return self._send(page.read_bytes(), ctype="text/html; charset=utf-8",
                              cache="no-cache")

        if path in ("/", "/index.html"):
            return shell()
        # static asset from the built app (e.g. /assets/index-xxxx.js)
        target = (DIST / path.lstrip("/")).resolve()
        if DIST.exists() and str(target).startswith(str(DIST.resolve())) and target.is_file():
            return self._send(target.read_bytes(),
                              ctype=_MIME.get(target.suffix, "application/octet-stream"),
                              cache="max-age=31536000, immutable")
        # not a file: an asset request or anything with an extension is an honest
        # 404; an extension-less path is an app route → hand back the shell
        last = path.rsplit("/", 1)[-1]
        if path.startswith("/assets/") or "." in last:
            return self._send({"error": "not found"}, 404)
        return shell()

    def _serve_pdf(self, key):
        """Stream a paper's PDF straight from library/ for the viewer."""
        lib = (Path(self.root) / "library").resolve()
        src = (lib / f"{key}.pdf").resolve()
        if not str(src).startswith(str(lib)) or not src.is_file():
            return self._send({"error": f"no PDF for {key!r}"}, 404, cache="no-store")
        return self._send(src.read_bytes(), ctype="application/pdf",
                          cache="private, max-age=3600")

    # --- GET ---
    def do_GET(self):
        path = urlparse(self.path).path
        try:
            parts = path.strip("/").split("/")
            if parts[:2] == ["api", "paper"] and len(parts) == 4 and parts[3] == "pdf":
                return self._serve_pdf(unquote(parts[2]))
            if path.startswith("/api/"):
                con = db.connect(self.root)
                try:
                    # no-store: browsers heuristically cache header-less JSON,
                    # which resurrects deleted rows after a refresh
                    return self._send(self._get_api(con, path), cache="no-store")
                finally:
                    con.close()
            self._serve_app(path)
        except Exception as exc:
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 400, cache="no-store")

    def _get_api(self, con, path):
        parts = path.strip("/").split("/")           # ['api', ...]
        if path == "/api/overview":
            return _overview(con)
        if path == "/api/papers":
            return _papers(con, self.root)
        if parts[:2] == ["api", "paper"] and len(parts) == 4 and parts[3] == "anchors":
            q = parse_qs(urlparse(self.path).query)
            return _paper_anchors(con, self.root, unquote(parts[2]),
                                  q.get("project", [None])[0])
        if parts[:2] == ["api", "paper"] and len(parts) == 4 and parts[3] == "references":
            from . import bibliography
            return {"references": bibliography.list_references(con, unquote(parts[2]))}
        if path == "/api/inbox":
            from . import bibliography
            return bibliography.inbox(con)
        if parts[:3] == ["api", "paper", "doc"] and len(parts) == 4:
            from . import paper_doc
            return paper_doc.get_doc(con, int(parts[3]))
        if parts[:2] == ["api", "paper"] and len(parts) == 4 and parts[3] == "docs":
            from . import paper_doc
            q = parse_qs(urlparse(self.path).query)
            return paper_doc.list_for_paper(con, unquote(parts[2]), q.get("project", [None])[0])
        if path == "/api/metric_defs":
            return experiment.metric_defs(con)
        if path == "/api/conferences":
            from . import conferences
            return conferences.fetch(self.root)
        if path == "/api/remotes":
            from . import remote as remotemod
            return remotemod.list_remotes(con)
        if path == "/api/sources":
            # distinct feedback/entry authors (people), for consistent labels;
            # system writers are not people
            return [r["source"] for r in con.execute(
                "SELECT DISTINCT source FROM log_entry WHERE source IS NOT NULL "
                "AND source NOT IN ('cockpit', 'scaffold') ORDER BY source")]
        if path == "/api/rubric":
            from .review import RUBRIC
            return RUBRIC
        if path == "/api/connections":
            from . import links as linksmod
            return [{"from": f, "to": t,
                     "options": [{"value": v, "label": lbl, "mode": m}
                                 for v, lbl, m in rels]}
                    for (f, t), rels in linksmod.CONNECTIONS.items()]
        if path == "/api/config/files":
            q = parse_qs(urlparse(self.path).query)
            return _config_listing(self.root, con, (q.get("project", [None])[0]))
        if path == "/api/config/file":
            q = parse_qs(urlparse(self.path).query)
            p = _config_path(self.root, con, q["scope"][0], q["name"][0],
                             (q.get("project", [None])[0]))
            return {"content": p.read_text(encoding="utf-8") if p.exists() else ""}
        if parts[:2] == ["api", "health"] and len(parts) == 3:
            return _health(con, self.root, unquote(parts[2]))
        if parts[:2] == ["api", "plan"] and len(parts) == 3:
            return _plan(con, unquote(parts[2]))
        if parts[:2] == ["api", "project"] and len(parts) == 4 and parts[3] == "runs":
            return _runs(con, unquote(parts[2]))
        if parts[:2] == ["api", "project"] and len(parts) == 3:
            return _project(con, unquote(parts[2]))
        if parts[:2] == ["api", "graph"] and len(parts) == 3:
            return _graph(con, self.root, unquote(parts[2]))
        if parts[:2] == ["api", "argument"] and len(parts) == 3:
            from . import argument
            return argument.analyze(con, unquote(parts[2]))
        if parts[:2] == ["api", "regions"] and len(parts) == 3:
            return _regions(con, unquote(parts[2]))
        if parts[:2] == ["api", "phases"] and len(parts) == 3:
            from . import phases as phasesmod
            return phasesmod.list_phases(con, unquote(parts[2]))
        if path.startswith("/api/search"):
            from . import search as searchmod
            q = parse_qs(urlparse(self.path).query)
            return searchmod.search(con, (q.get("q", [""])[0]),
                                    project=(q.get("project", [None])[0]))
        if parts[:2] == ["api", "paper"] and parts[-1] == "usage":
            return ingest.paper_usage(con, unquote(parts[2]))
        if parts[:2] == ["api", "finding"] and len(parts) == 3:
            return findmod.get_finding(con, int(parts[2]))
        if parts[:2] == ["api", "claim"] and len(parts) == 3:
            return claimmod.get_claim(con, int(parts[2]))
        raise ValueError(f"unknown endpoint {path}")

    # --- POST (writes go through the same domain functions as CLI/MCP) ---
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            con = db.connect(self.root)
            try:
                self._send(self._post_api(con, path, data), cache="no-store")
            finally:
                con.close()
        except Exception as exc:
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 400, cache="no-store")

    def _post_api(self, con, path, d):
        if path == "/api/finding/adjudicate":
            return findmod.adjudicate(con, d["id"], d["verdict"], d["reasoning"],
                                      by=d.get("by", "cockpit"))
        if path == "/api/note":
            return logmod.add_note(con, d["project"], d["body"], title=d.get("title"))
        if path == "/api/log":
            return logmod.add_entry(con, d["project"], d["type"], d["body"],
                                    experiment=d.get("experiment"),
                                    answers=d.get("answers"), source=d.get("source"))
        if path == "/api/plan":
            from . import plan as planmod
            return planmod.add_item(con, d["project"], d["title"], due=d["due"],
                                    kind=d.get("kind", "phase"),
                                    start=d.get("start"), note=d.get("note"),
                                    end_deadline=bool(d.get("end_deadline")),
                                    prepared=bool(d.get("prepared")),
                                    parent_id=d.get("parent_id"))
        if path == "/api/plan/update":
            from . import plan as planmod
            fields = {k: d[k] for k in ("title", "start", "due", "status", "note",
                                        "prepared", "end_deadline") if k in d}
            return planmod.update_item(con, d["id"], **fields)
        if path == "/api/plan/delete":
            from . import plan as planmod
            planmod.delete_item(con, d["id"])
            return {"deleted": d["id"]}
        if path == "/api/log/edit":
            return logmod.update_entry(con, d["id"], d["body"])
        if path == "/api/note/edit":
            return logmod.update_note(con, d["id"], d["body"], title=d.get("title"))
        if path == "/api/claim":
            return claimmod.add_claim(con, d["project"], d["text"],
                                      kind=d.get("kind", "assertion"))
        if path == "/api/link":
            from . import links as linksmod
            return linksmod.add_link(con, d["project"], from_kind=d["from_kind"],
                                     from_id=d["from_id"], to_kind=d["to_kind"],
                                     to_id=d["to_id"], relation=d["relation"],
                                     note=d.get("note"))
        if path == "/api/link/delete":
            from . import links as linksmod
            linksmod.delete_link(con, d["id"])
            return {"deleted": d["id"]}
        if path == "/api/claim/edit":
            return claimmod.update_text(con, d["id"], d["text"])
        if path == "/api/claim/link":
            return claimmod.link_evidence(con, d["claim_id"], citation_id=d.get("citation_id"),
                                          run_id=d.get("run_id"), stance=d.get("stance", "supports"),
                                          grade=d.get("grade", "suggestive"), note=d.get("note"))
        if path == "/api/claim/test":
            return claimmod.declare_test(con, d["project"], d["experiment"], d["claim_id"])
        if path == "/api/claim/test/delete":
            claimmod.undeclare_test(con, d["id"])
            return {"deleted": d["id"]}
        if path == "/api/claim/evidence/retract":
            return claimmod.retract_evidence(con, d["id"], d["reason"],
                                             superseded_by=d.get("superseded_by"))
        if path == "/api/claim/evidence/confirm":
            return claimmod.confirm_evidence(con, d["id"])
        if path == "/api/claim/relation/delete":
            claimmod.delete_relation(con, d["id"])
            return {"deleted": d["id"]}
        if path == "/api/lint":
            from . import lint
            return lint.run(con, d["project"])
        if path == "/api/phase_band":
            from . import phases as phasesmod
            return phasesmod.set_band(con, d["plan_item_id"], d["x0"], d["x1"])
        if path == "/api/phase_band/clear":
            from . import phases as phasesmod
            phasesmod.clear_band(con, d["plan_item_id"])
            return {"cleared": d["plan_item_id"]}
        if path == "/api/phase_band/color":
            from . import phases as phasesmod
            return phasesmod.set_color(con, d["plan_item_id"], d.get("color", ""))
        if path == "/api/paper/update":
            # metadata only (title) — the PDF, key, and anchors are immutable
            if not (d.get("title") or "").strip():
                raise ValueError("title must not be empty")
            if not con.execute("SELECT 1 FROM paper WHERE id=?", (d["id"],)).fetchone():
                raise KeyError(f"no paper #{d['id']}")
            con.execute("UPDATE paper SET title=? WHERE id=?", (d["title"].strip(), d["id"]))
            con.commit()
            return dict(con.execute("SELECT * FROM paper WHERE id=?", (d["id"],)).fetchone())
        if path == "/api/paper/add":
            src = (d.get("source") or "").strip()
            if not src:
                raise ValueError("source is required (a file path, arXiv id, or DOI)")
            return ingest.add(con, self.root, src, download=bool(d.get("download", True)))
        if path == "/api/paper/doc":
            from . import paper_doc
            return paper_doc.create_doc(con, d["key"], d.get("project"),
                                        title=d.get("title", "Untitled note"), body=d.get("body", ""))
        if path == "/api/paper/doc/update":
            from . import paper_doc
            fields = {k: d[k] for k in ("title", "body_md") if k in d}
            return paper_doc.update_doc(con, d["id"], **fields)
        if path == "/api/paper/doc/delete":
            from . import paper_doc
            paper_doc.delete_doc(con, d["id"])
            return {"deleted": d["id"]}
        if path == "/api/paper/note":
            from . import paper_note
            return paper_note.add_note(
                con, d["key"], d.get("project"), quote=d["quote"], body=d.get("body", ""),
                page=d.get("page"), prefix=d.get("prefix"), suffix=d.get("suffix"),
                src_start=d.get("src_start"), src_end=d.get("src_end"),
                color=d.get("color", "amber"), kind=d.get("kind", "note"))
        if path == "/api/paper/note/update":
            from . import paper_note
            fields = {k: d[k] for k in ("body_md", "color", "page", "kind") if k in d}
            return paper_note.update_note(con, d["id"], **fields)
        if path == "/api/reference/build":
            from . import bibliography
            bibliography.build_references(con, self.root, d["key"])
            return {"references": bibliography.list_references(con, d["key"])}
        if path == "/api/reference/mark":
            from . import bibliography
            return bibliography.mark_reference(con, d["id"], d.get("verdict"),
                                               d.get("comment"))
        if path == "/api/reference/add":
            from . import bibliography
            res = bibliography.add_reference(con, self.root, d["id"],
                                             download=d.get("download", True))
            return {"paper": res["paper"], "landed": res["landed"],
                    "reindex": res["reindex"]}
        if path == "/api/paper/read":
            from . import bibliography
            return bibliography.mark_read(con, d["key"])
        if path == "/api/paper/note/delete":
            from . import links as linksmod
            from . import paper_note
            # remember the project so this pnote's soft links don't go dangling
            row = con.execute(
                "SELECT p.slug FROM paper_note n JOIN project p ON p.id=n.project_id "
                "WHERE n.id=?", (d["id"],)).fetchone()
            paper_note.delete_note(con, d["id"])
            if row:
                linksmod.prune_dangling(con, row["slug"])
            return {"deleted": d["id"]}
        if path == "/api/region":
            from . import regions
            return regions.add_region(con, d["project"], x=d["x"], y=d["y"],
                                      w=d.get("w", 360), h=d.get("h", 240),
                                      label=d.get("label", ""), color=d.get("color", "slate"))
        if path == "/api/region/update":
            from . import regions
            fields = {k: d[k] for k in ("label", "color", "x", "y", "w", "h",
                                        "plan_item_id") if k in d}
            return regions.update_region(con, d["id"], **fields)
        if path == "/api/region/delete":
            from . import regions
            regions.delete_region(con, d["id"])
            return {"deleted": d["id"]}
        if path == "/api/graph/layout":
            pid = db.project_id(con, d["project"])
            for nid, p in (d.get("positions") or {}).items():
                con.execute(
                    "INSERT INTO graph_layout (project_id, node_id, x, y) VALUES (?,?,?,?) "
                    "ON CONFLICT(project_id, node_id) DO UPDATE SET x=excluded.x, y=excluded.y",
                    (pid, nid, float(p["x"]), float(p["y"])))
            con.commit()
            return {"saved": len(d.get("positions") or {})}
        if path == "/api/claim/relate":
            return claimmod.relate(con, d["claim_id"], d["related_id"],
                                   kind=d.get("kind", "depends_on"), note=d.get("note"))
        if path == "/api/config/file":
            content = d.get("content", "")
            if len(content.encode()) > _CONFIG_MAX_BYTES:
                raise ValueError("file too large")
            p = _config_path(self.root, con, d["scope"], d["name"], d.get("project"))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"saved": str(p), "bytes": len(content.encode())}
        if path == "/api/remote":
            from . import remote as remotemod
            return remotemod.add_remote(con, d["name"], host=d.get("host"),
                                        data_root=d.get("data_root"),
                                        description=d.get("description"))
        if path == "/api/metric_def":
            return experiment.define_metric(
                con, d["name"], label=d.get("label"), unit=d.get("unit"),
                direction=d.get("direction", "maximize"), fmt=d.get("fmt", ".3f"),
                description=d.get("description"))
        if path == "/api/project/settings":
            if d.get("status") not in (None, "active", "archived"):
                raise ValueError("status must be active or archived")
            pid = db.project_id(con, d["slug"])
            if d.get("title") is not None:
                con.execute("UPDATE project SET title=? WHERE id=?", (d["title"], pid))
            if d.get("status") is not None:
                con.execute("UPDATE project SET status=? WHERE id=?", (d["status"], pid))
            con.commit()
            return dict(con.execute("SELECT * FROM project WHERE id=?", (pid,)).fetchone())
        # full project creation — same path as `renv new`: DB row + template
        # scaffold under projects/<slug> + its own git repo
        if path == "/api/project":
            import subprocess
            from . import authoring
            slug = (d.get("slug") or "").strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", slug):
                raise ValueError("slug must be lowercase letters/digits/hyphens, e.g. 005-my-idea")
            title = (d.get("title") or "").strip() or slug
            pid = db.ensure_project(con, slug, title=title)
            authoring.scaffold_from_template(self.root, slug, title)
            proot = Path(self.root) / "projects" / slug
            if not (proot / ".git").exists():
                try:
                    subprocess.run(["git", "init", "-q"], cwd=str(proot), timeout=10, check=True)
                except Exception:
                    pass
            authoring.seed_ideation(con, slug)   # plan starts as a graph node, not a file
            return {"id": pid, "slug": slug, "title": title}
        if path == "/api/experiment":
            return experiment.create_experiment(con, d["project"], d["slug"],
                                                title=d.get("title"),
                                                hypothesis=d.get("hypothesis"),
                                                parent=d.get("parent"))
        if path == "/api/experiment/parent":
            return experiment.set_parent(con, d["project"], d["slug"], d.get("parent"))
        if path == "/api/experiment/update":
            return experiment.update_meta(con, d["project"], d["slug"],
                                          title=d.get("title"), hypothesis=d.get("hypothesis"),
                                          new_slug=d.get("new_slug"))
        # graph gesture: experiment→claim becomes claim evidence via the
        # experiment's latest DONE run — §0: an edge needs a recorded run.
        if path == "/api/claim/link_experiment":
            pid = db.project_id(con, d["project"])
            run = con.execute(
                "SELECT r.id FROM run r JOIN experiment e ON e.id=r.experiment_id "
                "WHERE e.project_id=? AND e.slug=? AND r.status='done' "
                "ORDER BY r.id DESC LIMIT 1", (pid, d["experiment"])).fetchone()
            if not run:
                raise ValueError(
                    f"experiment {d['experiment']!r} has no completed run yet — "
                    "run it first; claim evidence must be a recorded run (§0)")
            return claimmod.link_evidence(con, d["claim_id"], run_id=run["id"],
                                          stance=d.get("stance", "supports"),
                                          grade=d.get("grade", "suggestive"),
                                          note=d.get("note"))
        raise ValueError(f"unknown endpoint {path}")


def _launchd_sockets(name: bytes = b"Listeners") -> list[int]:
    """ALL listening fds handed over by launchd for one socket key.

    A key bound to ``localhost`` yields one fd per address family (IPv4 + IPv6),
    so the cockpit answers whichever stack the browser reaches for. Safari
    prefers IPv6; serving both loopback families is what makes a hosts-file
    override actually stick there, not just in Chrome.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    fds = ctypes.POINTER(ctypes.c_int)()
    count = ctypes.c_size_t(0)
    rc = libc.launch_activate_socket(name, ctypes.byref(fds), ctypes.byref(count))
    if rc != 0 or count.value == 0:
        raise OSError(rc, f"launch_activate_socket({name!r}) failed — not started by launchd?")
    out = [fds[i] for i in range(count.value)]
    libc.free(fds)
    return out


class _Redirect(BaseHTTPRequestHandler):
    """Port-80 companion when the cockpit is https: 301 to the SAME host over
    https. Echoing the requested Host (not a baked-in domain) is what lets one
    server front several local domains at once (research.test AND research.com)."""

    def log_message(self, *a):
        pass

    def _go(self):
        host = (self.headers.get("Host") or "localhost").split(":")[0]
        self.send_response(301)
        self.send_header("Location", f"https://{host}{self.path}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_HEAD = do_POST = _go


def _tls_context(tls_cert: str, tls_key: str):
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tls_cert, tls_key)
    return ctx


def _server_for(family: int, addr: str, port: int, handler, ctx=None):
    """A loopback ThreadingHTTPServer bound to one address family, TLS-wrapped."""
    class _S(ThreadingHTTPServer):
        address_family = family
    srv = _S((addr, port), handler)
    if ctx:
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv


def _adopt(fd: int, handler, port: int, ctx=None):
    """Wrap a ThreadingHTTPServer around an already-listening launchd fd."""
    srv = ThreadingHTTPServer(("", port), handler, bind_and_activate=False)
    s = socketmod.socket(fileno=fd)
    srv.socket = ctx.wrap_socket(s, server_side=True) if ctx else s
    return srv


def serve(root=".", port: int = 8765, host: str = "127.0.0.1", *,
          idle_exit: int | None = None, launchd: bool = False,
          tls_cert: str | None = None, tls_key: str | None = None,
          domain: str | None = None) -> None:
    """Serve the cockpit on loopback. Dual-stack: under launchd we adopt every
    fd launchd hands us (IPv4 + IPv6); standalone we bind both 127.0.0.1 and
    ::1. TLS-wrapped when a cert is given; an http→https redirect rides the
    :80 socket(s). ``domain`` is unused (the redirect echoes the Host)."""
    db.connect(root).close()  # ensure DB exists/migrated
    Handler.root = root
    ctx = _tls_context(tls_cert, tls_key) if tls_cert else None

    servers: list = []
    if launchd:
        fds = _launchd_sockets(b"Listeners")
        servers = [_adopt(fd, Handler, port, ctx) for fd in fds]
        print(f"renv cockpit (launchd-activated, {len(fds)} socket(s), "
              f"idle-exit {idle_exit or '-'}s)")
        if ctx:                      # bounce http→https on every :80 fd we got
            try:
                rfds = _launchd_sockets(b"Redirect")
            except OSError:
                rfds = []
            for fd in rfds:
                threading.Thread(target=_adopt(fd, _Redirect, 80).serve_forever,
                                 daemon=True).start()
    else:
        # bind loopback on both stacks; IPv6 is best-effort (some hosts lack it)
        for family, addr in ((socketmod.AF_INET, "127.0.0.1"),
                             (socketmod.AF_INET6, "::1")):
            try:
                servers.append(_server_for(family, addr, port, Handler, ctx))
            except OSError:
                if family == socketmod.AF_INET:
                    raise            # v4 loopback is mandatory; v6 is a bonus
        scheme = "https" if ctx else "http"
        print(f"renv cockpit → {scheme}://{host}:{port}   (Ctrl-C to stop)")

    if not servers:
        raise RuntimeError("no listening sockets")

    if idle_exit:
        Handler.last_activity = time.monotonic()

        def watchdog():
            interval = max(1, min(15, idle_exit // 2))
            while True:
                time.sleep(interval)
                if time.monotonic() - Handler.last_activity > idle_exit:
                    print(f"idle {idle_exit}s — exiting (launchd re-arms the socket)")
                    for s in servers:
                        s.shutdown()
                    return

        threading.Thread(target=watchdog, daemon=True).start()

    for srv in servers[1:]:          # all but one in threads, last in main
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


# --- on-demand install (launchd LaunchAgent + socket activation) -------------
# SockNodeName "localhost" resolves to BOTH 127.0.0.1 and ::1, so launchd hands
# us one fd per family and the cockpit answers IPv4 and IPv6 loopback alike —
# the dual-stack that makes Safari honor the local override.
_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>com.renv.web</string>
    <key>ProgramArguments</key><array>
        <string>{python}</string><string>-m</string><string>renv.cli</string>
        <string>web</string><string>--launchd</string>
        <string>--idle-exit</string><string>{idle}</string>{tls_args}
    </array>
    <key>WorkingDirectory</key><string>{root}</string>
    <key>Sockets</key><dict>{sockets}</dict>
    <key>StandardOutPath</key><string>{root}/.research/web.log</string>
    <key>StandardErrorPath</key><string>{root}/.research/web.log</string>
    <key>RunAtLoad</key><false/>
</dict></plist>
"""

_SOCK = ("<key>{name}</key><dict>"
         "<key>SockNodeName</key><string>localhost</string>"
         "<key>SockServiceName</key><string>{port}</string></dict>")

# managed block markers in /etc/hosts — everything between is ours to rewrite
_HOSTS = Path("/etc/hosts")
_HOSTS_BEGIN = "# >>> renv cockpit (managed — renv web install) >>>"
_HOSTS_END = "# <<< renv cockpit (managed) <<<"

# reserved / loopback TLDs that carry no public DNS, so a hosts override is the
# ONLY answer a browser can get — the recipe that "just works" in every browser
_SAFE_TLDS = (".test", ".localhost", ".local", ".example", ".invalid")


def is_safe_domain(domain: str) -> bool:
    return any(domain == t.lstrip(".") or domain.endswith(t) for t in _SAFE_TLDS)


def _ensure_cert(root, domains: list[str]) -> tuple[Path, Path]:
    """Mint one locally-trusted TLS cert covering ALL domains (multi-SAN) via
    mkcert. Re-mints only when the requested set changes (a sidecar records it).

    mkcert keeps a local root CA; `mkcert -install` (one-time, keychain prompt)
    makes browsers trust it — the only way to get a padlock for a domain you
    don't own, since no public CA will sign it.
    """
    import shutil
    import subprocess
    tls = Path(root) / ".research" / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    primary = domains[0]
    cert, key = tls / f"{primary}.pem", tls / f"{primary}-key.pem"
    marker = tls / f"{primary}.domains"
    want = "\n".join(domains)
    if cert.exists() and key.exists() and marker.exists() and marker.read_text() == want:
        return cert, key
    mkcert = shutil.which("mkcert")
    if not mkcert:
        raise RuntimeError("mkcert not found — `brew install mkcert`, then re-run")
    subprocess.run([mkcert, "-cert-file", str(cert), "-key-file", str(key), *domains],
                   check=True, capture_output=True, text=True)
    marker.write_text(want)
    return cert, key


def _install_local_ca() -> None:
    """`mkcert -install` — idempotent; trusts the local CA so browsers show a
    padlock (may prompt for the keychain password the first time)."""
    import shutil
    import subprocess
    mkcert = shutil.which("mkcert")
    if mkcert:
        subprocess.run([mkcert, "-install"], check=False)


def hosts_block(domains: list[str]) -> str:
    lines = [_HOSTS_BEGIN]
    for d in domains:                       # both stacks: Safari reaches for ::1
        lines += [f"127.0.0.1 {d}", f"::1 {d}"]
    lines.append(_HOSTS_END)
    return "\n".join(lines)


def compose_hosts(current: str, domains: list[str]) -> str:
    """Current /etc/hosts with our managed block (and any stray loopback lines
    for these domains) replaced by one clean, deduped block. Idempotent."""
    dset = set(domains)
    out, skip = [], False
    for ln in current.splitlines():
        s = ln.strip()
        if s == _HOSTS_BEGIN:
            skip = True
            continue
        if s == _HOSTS_END:
            skip = False
            continue
        if skip:
            continue
        parts = s.split()                   # drop stray dupes we'd re-add anyway
        if len(parts) >= 2 and parts[0] in ("127.0.0.1", "::1") and dset & set(parts[1:]):
            continue
        out.append(ln)
    body = "\n".join(out).rstrip()
    return f"{body}\n\n{hosts_block(domains)}\n"


def update_hosts(domains: list[str], *, apply: bool = True) -> bool:
    """Rewrite /etc/hosts to map each domain to loopback (v4+v6). Returns True
    if a change was applied. The write uses one sudo call (prompts in the
    terminal, backs up once) — never silent. apply=False just reports."""
    current = _HOSTS.read_text() if _HOSTS.exists() else ""
    desired = compose_hosts(current, domains)
    if current == desired:
        return False
    if not apply:
        return True
    import subprocess
    import tempfile
    if not (_HOSTS.parent / "hosts.renv.bak").exists():
        subprocess.run(["sudo", "cp", str(_HOSTS), "/etc/hosts.renv.bak"], check=True)
    with tempfile.NamedTemporaryFile("w", suffix=".hosts", delete=False) as tf:
        tf.write(desired)
        tmp = tf.name
    subprocess.run(["sudo", "cp", tmp, str(_HOSTS)], check=True)  # keeps root:wheel
    Path(tmp).unlink(missing_ok=True)
    _flush_dns()
    return True


def _flush_dns() -> None:
    """Drop cached lookups so a just-added host resolves immediately — otherwise
    macOS/Safari can keep serving the old NXDOMAIN and the domain looks dead."""
    import subprocess
    subprocess.run(["dscacheutil", "-flushcache"], check=False)
    subprocess.run(["sudo", "killall", "-HUP", "mDNSResponder"], check=False)


def install_launch_agent(root=".", *, domains: list[str] | None = None,
                         port: int = 443, idle: int = 1800, https: bool = True,
                         edit_hosts: bool = True) -> dict:
    """One-shot install: mint a multi-SAN cert, trust the local CA, map every
    domain to loopback in /etc/hosts, and load a socket-activated LaunchAgent
    that starts the cockpit on the first request and idle-exits. Returns a
    summary dict. Nothing runs in the background until a browser knocks."""
    import subprocess
    domains = list(domains or ["research.test"])
    root = str(Path(root).resolve())
    # the agent bakes this path in — refuse anything that isn't the env root,
    # else the server would silently open a fresh empty DB somewhere else
    if not (Path(root) / "renv").is_dir():
        raise RuntimeError(
            f"{root} is not the research-env root (no renv/ package) — "
            "run from the repo root or pass --corpus")

    tls_args, cert = "", None
    if https:
        _install_local_ca()
        cert, key = _ensure_cert(root, domains)
        sockets = (_SOCK.format(name="Listeners", port=443)
                   + _SOCK.format(name="Redirect", port=80))
        tls_args = (f"\n        <string>--tls-cert</string><string>{cert}</string>"
                    f"\n        <string>--tls-key</string><string>{key}</string>")
    else:
        sockets = _SOCK.format(name="Listeners", port=port)

    hosts_changed = update_hosts(domains, apply=True) if edit_hosts else False

    plist = Path.home() / "Library" / "LaunchAgents" / "com.renv.web.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(_PLIST.format(python=sys.executable, root=root,
                                   idle=idle, sockets=sockets, tls_args=tls_args))
    uid = __import__("os").getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/com.renv.web"],
                   capture_output=True)   # reload-safe: drop any old version
    for attempt in range(4):              # bootout drains async — retry briefly
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            scheme = "https" if https else "http"
            suffix = "" if (https or port == 80) else f":{port}"
            return {"plist": str(plist), "domains": domains, "https": https,
                    "hosts_changed": hosts_changed, "idle": idle,
                    "urls": [f"{scheme}://{d}{suffix}/" for d in domains]}
        time.sleep(1 + attempt)
    raise RuntimeError(f"launchctl bootstrap failed: {r.stderr.strip() or r.returncode}")


def uninstall_launch_agent(*, edit_hosts: bool = True) -> bool:
    import subprocess
    plist = Path.home() / "Library" / "LaunchAgents" / "com.renv.web.plist"
    uid = __import__("os").getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/com.renv.web"],
                   capture_output=True)
    if edit_hosts and _HOSTS.exists():     # strip our managed block, keep the rest
        current = _HOSTS.read_text()
        if _HOSTS_BEGIN in current:
            cleaned, skip = [], False
            for ln in current.splitlines():
                s = ln.strip()
                if s == _HOSTS_BEGIN:
                    skip = True
                    continue
                if s == _HOSTS_END:
                    skip = False
                    continue
                if not skip:
                    cleaned.append(ln)
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".hosts", delete=False) as tf:
                tf.write("\n".join(cleaned).rstrip() + "\n")
                tmp = tf.name
            subprocess.run(["sudo", "cp", tmp, str(_HOSTS)], check=True)
            Path(tmp).unlink(missing_ok=True)
    if plist.exists():
        plist.unlink()
        return True
    return False
