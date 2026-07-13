"""The web cockpit — a minimal local dashboard over the single SQLite ground truth.

Pure stdlib ``http.server`` (no framework, no build step): the *human* interface
that mirrors what an agent does via MCP. Every write goes through the same domain
functions as the CLI, so the §0 constraints hold whoever acts, and the page and the
agent see identical live state. Binds to 127.0.0.1 only.

Views: dashboard, papers + citation usage map, the experiment branch (DAG)
explorer, findings with accept/reject adjudication, the claim/evidence graph, and a
timeline of decisions + notes.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import claim as claimmod
from . import db, experiment, ingest
from . import finding as findmod
from . import log as logmod

WEB_DIR = Path(__file__).parent / "web"
DIST = Path(__file__).parent.parent / "cockpit" / "dist"   # built React Flow app (if present)
_MIME = {".js": "text/javascript", ".css": "text/css", ".html": "text/html",
         ".svg": "image/svg+xml", ".json": "application/json", ".map": "application/json"}


def _graph(con, root, slug):
    """A unified node/edge graph for a project: experiment DAG + claims + findings +
    citations + papers + code references, ready for a graph UI (React Flow). Neutral
    shape; the client lays it out (dagre) and maps kinds to node components."""
    pid = db.project_id(con, slug)
    nodes, edges, seen = [], [], set()

    def node(nid, kind, label, data):
        if nid in seen:
            return
        seen.add(nid)
        nodes.append({"id": nid, "kind": kind, "label": label, "data": data})

    for e in experiment.list_experiments(con, slug):
        node(f"exp:{e['id']}", "experiment", e["slug"],
             {"title": e["title"], "status": e["status"], "metrics": e["metrics"],
              "hypothesis": e["hypothesis"]})
        if e["parent_id"]:
            edges.append({"source": f"exp:{e['parent_id']}", "target": f"exp:{e['id']}", "kind": "parent"})

    for c in con.execute(
            "SELECT c.id, c.paper_id, c.support, c.quote, p.key FROM citation c "
            "LEFT JOIN paper p ON p.id=c.paper_id WHERE c.project_id=?", (pid,)).fetchall():
        node(f"cite:{c['id']}", "citation", (c["key"] or "cite") + f"#{c['id']}",
             {"support": c["support"], "quote": c["quote"]})
        if c["paper_id"]:
            node(f"paper:{c['paper_id']}", "paper", c["key"], {})
            edges.append({"source": f"paper:{c['paper_id']}", "target": f"cite:{c['id']}", "kind": "cited"})

    for c in claimmod.list_claims(con, slug):
        full = claimmod.get_claim(con, c["id"])
        node(f"claim:{c['id']}", "claim", c["text"][:48],
             {"kind": c["kind"], "status": c["status"], "text": c["text"]})
        for ev in full["evidence"]:
            if ev["run_id"]:
                r = con.execute("SELECT experiment_id FROM run WHERE id=?", (ev["run_id"],)).fetchone()
                if r:
                    edges.append({"source": f"exp:{r['experiment_id']}", "target": f"claim:{c['id']}", "kind": ev["stance"]})
            if ev["citation_id"]:
                edges.append({"source": f"cite:{ev['citation_id']}", "target": f"claim:{c['id']}", "kind": ev["stance"]})

    for f in findmod.list_findings(con, slug, status="open"):
        node(f"finding:{f['id']}", "finding", f["check_id"],
             {"severity": f["severity"], "issue": f["issue"], "status": f["status"]})
        for ev in con.execute("SELECT citation_id FROM finding_evidence WHERE finding_id=?", (f["id"],)).fetchall():
            if ev["citation_id"]:
                edges.append({"source": f"finding:{f['id']}", "target": f"cite:{ev['citation_id']}", "kind": "about"})

    _add_code_refs(con, root, pid, nodes, edges, seen, node)
    return {"slug": slug, "nodes": nodes, "edges": edges}


def _add_code_refs(con, root, pid, nodes, edges, seen, node):
    """Add @reref code tags that point at a node already in this graph (code↔store)."""
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
        "SELECT slug, title, status FROM project ORDER BY slug")]
    counts = {t: con.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
              for t in ("paper", "experiment", "run", "citation", "claim", "finding", "note")}
    for p in projects:
        p["open_findings"] = con.execute(
            "SELECT COUNT(*) n FROM finding WHERE status='open' AND "
            "project_id=(SELECT id FROM project WHERE slug=?)", (p["slug"],)).fetchone()["n"]
    return {"projects": projects, "counts": counts}


def _project(con, slug):
    pid = db.project_id(con, slug)
    notes = [dict(r) for r in con.execute(
        "SELECT * FROM note WHERE project_id=? ORDER BY id DESC", (pid,))]
    return {
        "slug": slug,
        "experiments": experiment.list_experiments(con, slug),
        "findings": findmod.list_findings(con, slug),
        "claims": claimmod.list_claims(con, slug),
        "log": logmod.list_entries(con, slug, limit=100),
        "notes": notes,
    }


class Handler(BaseHTTPRequestHandler):
    root = "."

    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, obj, status=200, ctype="application/json"):
        body = obj if isinstance(obj, (bytes, bytearray)) else json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")  # local dev: Vite on :5173
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # CORS preflight
        self._send(b"", 204, "text/plain")

    def _serve_app(self, path):
        """Serve the built React Flow app from cockpit/dist if present, else the
        simple buildless page. Static assets come from dist/."""
        if path in ("/", "/index.html"):
            page = DIST / "index.html" if (DIST / "index.html").exists() else WEB_DIR / "index.html"
            return self._send(page.read_bytes(), ctype="text/html; charset=utf-8")
        # static asset from the built app (e.g. /assets/index-xxxx.js)
        target = (DIST / path.lstrip("/")).resolve()
        if DIST.exists() and str(target).startswith(str(DIST.resolve())) and target.is_file():
            return self._send(target.read_bytes(), ctype=_MIME.get(target.suffix, "application/octet-stream"))
        self._send({"error": "not found"}, 404)

    # --- GET ---
    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                con = db.connect(self.root)
                try:
                    return self._send(self._get_api(con, path))
                finally:
                    con.close()
            self._serve_app(path)
        except Exception as exc:
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 400)

    def _get_api(self, con, path):
        parts = path.strip("/").split("/")           # ['api', ...]
        if path == "/api/overview":
            return _overview(con)
        if path == "/api/papers":
            return ingest.list_papers(con)
        if parts[:2] == ["api", "project"] and len(parts) == 3:
            return _project(con, unquote(parts[2]))
        if parts[:2] == ["api", "graph"] and len(parts) == 3:
            return _graph(con, self.root, unquote(parts[2]))
        if path.startswith("/api/search"):
            from urllib.parse import parse_qs
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
                self._send(self._post_api(con, path, data))
            finally:
                con.close()
        except Exception as exc:
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 400)

    def _post_api(self, con, path, d):
        if path == "/api/finding/adjudicate":
            return findmod.adjudicate(con, d["id"], d["verdict"], d["reasoning"],
                                      by=d.get("by", "cockpit"))
        if path == "/api/note":
            return logmod.add_note(con, d["project"], d["body"], title=d.get("title"))
        if path == "/api/claim/link":
            return claimmod.link_evidence(con, d["claim_id"], citation_id=d.get("citation_id"),
                                          run_id=d.get("run_id"), stance=d.get("stance", "supports"),
                                          note=d.get("note"))
        raise ValueError(f"unknown endpoint {path}")


def serve(root=".", port: int = 8765, host: str = "127.0.0.1") -> None:
    db.connect(root).close()  # ensure DB exists/migrated
    Handler.root = root
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"reref cockpit → http://{host}:{port}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
