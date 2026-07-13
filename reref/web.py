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
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

_LOCAL_ORIGIN = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")

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
                    edges.append({"source": f"exp:{r['experiment_id']}", "target": f"claim:{c['id']}",
                                  "kind": ev["stance"], "note": ev["note"]})
            if ev["citation_id"]:
                edges.append({"source": f"cite:{ev['citation_id']}", "target": f"claim:{c['id']}",
                              "kind": ev["stance"], "note": ev["note"]})
    for rel in claimmod.list_relations(con, slug):
        edges.append({"source": f"claim:{rel['claim_id']}",
                      "target": f"claim:{rel['related_id']}", "kind": rel["kind"],
                      "note": rel["note"]})

    # thinking made visible: questions / hypotheses / feedback join the graph,
    # wired to the experiment they concern and to the entries that answer them
    thought_rows = con.execute(
        "SELECT * FROM log_entry WHERE project_id=? AND ("
        "type IN ('question','hypothesis','feedback') OR answers IS NOT NULL) "
        "ORDER BY id", (pid,)).fetchall()
    for e in thought_rows:
        answered = None
        if e["type"] == "question":
            a = con.execute("SELECT 1 FROM log_entry WHERE answers=?", (e["id"],)).fetchone()
            answered = bool(a)
        node(f"log:{e['id']}", e["type"] if e["type"] in ("question", "hypothesis", "feedback")
             else "thought",
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
    # the §0 ledger indicator: does every result entry trace to a run?
    violations = logmod.check_invariants(con)
    return {"projects": projects, "counts": counts,
            "invariants": {"clean": not violations, "violations": len(violations)}}


def _runs(con, slug):
    """All runs of a project (newest first) with params, dataset, and metrics —
    the raw material for the cockpit's runs ledger."""
    pid = db.project_id(con, slug)
    runs = [dict(r) for r in con.execute(
        "SELECT r.id, r.status, r.started, r.finished, r.seed, r.git_sha, "
        "       r.dirty, r.provenance, r.entrypoint, e.slug AS experiment, "
        "       c.params_json, d.slug AS dataset "
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


# --- admin control surface: the files agents actually read -------------------
# STRICT allowlist. These are the real levers of the environment: AGENTS.md is
# what an agent loads at session start, templates/ is what every `reref new`
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

    def log_message(self, *a):  # keep the console quiet
        pass

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
        simple buildless page. Static assets come from dist/."""
        if path in ("/", "/index.html"):
            page = DIST / "index.html" if (DIST / "index.html").exists() else WEB_DIR / "index.html"
            # never cache the shell: it references hash-named bundles that
            # change on every rebuild — a cached shell shows a stale app
            return self._send(page.read_bytes(), ctype="text/html; charset=utf-8",
                              cache="no-cache")
        # static asset from the built app (e.g. /assets/index-xxxx.js)
        target = (DIST / path.lstrip("/")).resolve()
        if DIST.exists() and str(target).startswith(str(DIST.resolve())) and target.is_file():
            return self._send(target.read_bytes(),
                              ctype=_MIME.get(target.suffix, "application/octet-stream"),
                              cache="max-age=31536000, immutable")
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
        if path == "/api/metric_defs":
            return experiment.metric_defs(con)
        if path == "/api/rubric":
            from .review import RUBRIC
            return RUBRIC
        if path == "/api/config/files":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            return _config_listing(self.root, con, (q.get("project", [None])[0]))
        if path == "/api/config/file":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            p = _config_path(self.root, con, q["scope"][0], q["name"][0],
                             (q.get("project", [None])[0]))
            return {"content": p.read_text(encoding="utf-8") if p.exists() else ""}
        if parts[:2] == ["api", "project"] and len(parts) == 4 and parts[3] == "runs":
            return _runs(con, unquote(parts[2]))
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
        if path == "/api/log":
            return logmod.add_entry(con, d["project"], d["type"], d["body"],
                                    experiment=d.get("experiment"),
                                    answers=d.get("answers"), source=d.get("source"))
        if path == "/api/claim":
            return claimmod.add_claim(con, d["project"], d["text"],
                                      kind=d.get("kind", "assertion"))
        if path == "/api/claim/link":
            return claimmod.link_evidence(con, d["claim_id"], citation_id=d.get("citation_id"),
                                          run_id=d.get("run_id"), stance=d.get("stance", "supports"),
                                          note=d.get("note"))
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
        # full project creation — same path as `reref new`: DB row + template
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
