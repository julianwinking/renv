"""Local stdio MCP server — exposes the engine + research DB as agent tools.

This is the third client over the single ground-truth store (see db.py), letting
Claude Code *drive* the research loop: search the corpus, cite claims, create and
run experiments, and append to the decision log. Every write goes through the same
domain functions as the CLI, so the §0 constraints hold no matter who calls.

Transport is the MCP stdio protocol — newline-delimited JSON-RPC 2.0 on
stdin/stdout — implemented in pure stdlib, so the server runs with zero extra
dependencies (consistent with the stdlib-first engine). Logs go to stderr only;
stdout carries protocol messages exclusively.

Register in .mcp.json:
    {"mcpServers": {"reref": {"command": "uv", "args": ["run", "reref", "mcp"]}}}
"""

from __future__ import annotations

import json
import sys

from . import db, experiment, log
from .dataset import list_datasets, register_dataset

SERVER_INFO = {"name": "reref", "version": "0.1.0"}
DEFAULT_PROTOCOL = "2025-06-18"

# One write-connection per server process (a long-lived stdio session must not leak
# a connection per tool call). The read-only `query` path opens its own short conn.
_CONN: dict[str, object] = {}


def _conn(root):
    from pathlib import Path
    key = str(Path(root).resolve())
    if key not in _CONN:
        _CONN[key] = db.connect(root)
    return _CONN[key]


# --- corpus retriever (lazy; mirrors the CLI loader but raises) ---------------
def _retriever(root, verifier: str = "lexical"):
    from .config import Lockfile
    from .embed import get_embedder
    from .project import Corpus
    from .retrieve import Retriever
    from .store import Index
    from .verify import get_verifier

    corpus = Corpus(root)
    if not corpus.is_indexed():
        raise RuntimeError("corpus is not indexed — run `reref index` first")
    lock = Lockfile.load(corpus.artifacts)
    index = Index.load(corpus.artifacts)
    embedder = get_embedder(lock.config.embedder, lock.config.embedder_model)
    if lock.config.embedder == "lexical":
        embedder.fit([r.text for r in index.records])
    return Retriever(index, embedder, get_verifier(verifier)), lock


# --- tool handlers: each takes (root, args) -> JSON-able result ---------------
def h_status(root, a):
    from .project import Corpus, Project
    corpus = Corpus(root)
    out = {"corpus": str(corpus.root), "indexed": corpus.is_indexed()}
    if a.get("project"):
        con = _conn(root)
        try:
            pid = db.project_id(con, a["project"])
            out["project"] = a["project"]
            out["experiments"] = experiment.list_experiments(con, a["project"])
            out["log_violations"] = log.check_invariants(con)
        except KeyError:
            out["project"] = f"(no project {a['project']!r})"
    return out


def h_search_corpus(root, a):
    r, _ = _retriever(root, a.get("verifier", "lexical"))
    cands = r.search(a["query"], top_k=a.get("top_k", 5), verify=a.get("verify", True))
    return [{
        "source_id": c.record.source_id,
        "start": c.record.start, "end": c.record.end,
        "similarity": round(c.similarity, 4),
        "support": c.verdict.support if c.verdict else None,
        "text": c.record.text,
    } for c in cands]


def h_cite_claim(root, a):
    from .cite import append_sidecar, make_citation
    from .project import Project
    r, lock = _retriever(root, a.get("verifier", "lexical"))
    hashes = {s.source_id: s.sha256 for s in lock.sources}
    cands = r.search(a["claim"], top_k=a.get("top_k", 5), verify=True)
    if not cands:
        return {"found": False}
    best = cands[0]
    cit = make_citation(a["claim"], best, hashes.get(best.record.source_id, ""))
    result = {"found": True, **cit.to_dict(), "latex": cit.latex()}
    if a.get("project") and a.get("write"):
        from . import ingest
        proj = Project(__import__("pathlib").Path(root) / "projects" / a["project"])
        try:  # citation table is source of truth; citations.json is derived
            con = _conn(root)
            db.project_id(con, a["project"])
            result["citation_id"] = ingest.record_citation(
                con, a["project"], cit, manuscript_loc=a.get("manuscript_loc"))["id"]
            result["sidecar"] = str(ingest.regenerate_sidecar(con, a["project"], proj.root))
        except KeyError:
            result["sidecar"] = str(append_sidecar(proj.root, cit))
    return result


def h_create_project(root, a):
    con = _conn(root)
    pid = db.ensure_project(con, a["slug"], title=a.get("title"))
    from .project import Project
    proj = Project(__import__("pathlib").Path(root) / "projects" / a["slug"])
    proj.ensure()
    (proj.root / "runs").mkdir(exist_ok=True)
    return {"id": pid, "slug": a["slug"]}


def h_list_experiments(root, a):
    return experiment.list_experiments(_conn(root), a["project"])


def h_get_experiment(root, a):
    con = _conn(root)
    exp = experiment.get_experiment(con, a["project"], a["slug"])
    if not exp:
        raise KeyError(f"no experiment {a['slug']!r} in {a['project']!r}")
    exp["runs"] = [
        {**run, "metrics": experiment.get_metrics(con, run["id"])}
        for run in experiment.list_runs(con, exp["id"])
    ]
    return exp


def h_create_experiment(root, a):
    return experiment.create_experiment(
        _conn(root), a["project"], a["slug"],
        title=a.get("title"), hypothesis=a.get("hypothesis"), parent=a.get("parent"))


def h_run_experiment(root, a):
    con = _conn(root)
    dataset_id = None
    if a.get("dataset"):
        from .dataset import get_dataset
        slug, _, ver = a["dataset"].partition("@")
        ds = get_dataset(con, slug, ver or "1")
        if not ds:
            raise KeyError(f"dataset {a['dataset']!r} not registered")
        dataset_id = ds["id"]
    run = experiment.run_experiment(
        con, a["project"], a["slug"], entrypoint=a["entrypoint"], root=root,
        params=a.get("params") or {}, dataset_id=dataset_id, seed=a.get("seed", 0),
        env_allow=a.get("env_allow"))
    run["metrics"] = experiment.get_metrics(con, run["id"])
    return run


def h_start_run(root, a):
    con = _conn(root)
    dataset_id = None
    if a.get("dataset"):
        from .dataset import get_dataset
        slug, _, ver = a["dataset"].partition("@")
        ds = get_dataset(con, slug, ver or "1")
        if not ds:
            raise KeyError(f"dataset {a['dataset']!r} not registered")
        dataset_id = ds["id"]
    return experiment.start_run(
        con, a["project"], a["slug"], entrypoint=a["entrypoint"], root=root,
        params=a.get("params") or {}, dataset_id=dataset_id, seed=a.get("seed", 0),
        env_allow=a.get("env_allow"))


def h_run_status(root, a):
    return experiment.run_status(_conn(root), a["run_id"])


def h_log_decision(root, a):
    return log.add_entry(
        _conn(root), a["project"], a["type"], a["body"],
        experiment=a.get("experiment"),
        runs=a.get("runs") or [], citations=a.get("citations") or [],
        answers=a.get("answers"), source=a.get("source"))


def h_list_log(root, a):
    return log.list_entries(_conn(root), a["project"], limit=a.get("limit", 50))


def h_check_invariants(root, a):
    return log.check_invariants(_conn(root))


def h_add_note(root, a):
    return log.add_note(_conn(root), a["project"], a["body"], title=a.get("title"))


def h_register_dataset(root, a):
    return register_dataset(
        _conn(root), a["slug"], version=a.get("version", "1"),
        path=a.get("path"), description=a.get("description"))


def h_scaffold_project(root, a):
    from pathlib import Path
    from . import authoring
    con = _conn(root)
    title = a.get("title") or a["slug"]
    pid = db.ensure_project(con, a["slug"], title=title)
    proot = Path(root) / "projects" / a["slug"]
    from .project import Project
    Project(proot).ensure()
    (proot / "runs").mkdir(exist_ok=True)
    authoring.scaffold_ideation(proot, title)
    written = authoring.scaffold_paper(proot, a["slug"], title)
    return {"id": pid, "slug": a["slug"], "scaffolded": [p.name for p in written]}


def h_weave(root, a):
    from pathlib import Path
    from . import authoring
    con = _conn(root)
    paths = authoring.weave(con, a["project"], Path(root) / "projects" / a["project"])
    return {"generated": [str(p) for p in paths]}


def h_add_paper(root, a):
    from . import ingest
    return ingest.add(_conn(root), root, a["source"],
                      key=a.get("key"), download=a.get("download", False))


def h_list_papers(root, a):
    from . import ingest
    return ingest.list_papers(_conn(root))


def h_discover_papers(root, a):
    from . import ingest
    return ingest.search_arxiv(a["query"], max_results=a.get("limit", 10))


def h_paper_usage(root, a):
    from . import ingest
    return ingest.paper_usage(_conn(root), a["key"])


def h_get_card(root, a):
    from . import extract
    con = _conn(root)
    card = extract.get_card(con, a["key"])
    if not card or a.get("refresh"):
        card = extract.extract_card(con, root, a["key"])
    return card


def h_review(root, a):
    from . import review
    return review.review(_conn(root), root, a["project"])


def h_rubric(root, a):
    from .review import RUBRIC
    return RUBRIC


def h_add_claim(root, a):
    from . import claim
    return claim.add_claim(_conn(root), a["project"], a["text"],
                           kind=a.get("kind", "assertion"), manuscript_loc=a.get("manuscript_loc"))


def h_link_claim_evidence(root, a):
    from . import claim
    return claim.link_evidence(_conn(root), a["claim_id"], citation_id=a.get("citation_id"),
                               run_id=a.get("run_id"), stance=a.get("stance", "supports"),
                               note=a.get("note"))


def h_relate_claims(root, a):
    from . import claim
    return claim.relate(_conn(root), a["claim_id"], a["related_id"],
                        kind=a.get("kind", "depends_on"), note=a.get("note"))


def h_list_claims(root, a):
    from . import claim
    return claim.list_claims(_conn(root), a["project"], status=a.get("status"))


def h_get_claim(root, a):
    from . import claim
    c = claim.get_claim(_conn(root), a["id"])
    if not c:
        raise KeyError(f"no claim #{a['id']}")
    return c


def h_set_experiment_status(root, a):
    experiment.set_status(_conn(root), a["project"], a["slug"], a["status"])
    return experiment.get_experiment(_conn(root), a["project"], a["slug"])


def h_scan_refs(root, a):
    from . import refs
    return refs.validate(_conn(root), refs.scan(root))


def h_code_refs_for(root, a):
    from . import refs
    return refs.code_refs_for(_conn(root), root, a["kind"], a["id"])


def h_list_findings(root, a):
    from . import finding
    return finding.list_findings(_conn(root), a["project"], status=a.get("status"))


def h_get_finding(root, a):
    from . import finding
    f = finding.get_finding(_conn(root), a["id"])
    if not f:
        raise KeyError(f"no finding #{a['id']}")
    return f


def h_adjudicate_finding(root, a):
    from . import finding
    return finding.adjudicate(_conn(root), a["id"], a["verdict"], a["reasoning"],
                              by=a.get("by", "agent"))


def h_search(root, a):
    from . import search as searchmod
    return searchmod.search(_conn(root), a["query"], project=a.get("project"),
                            limit=a.get("limit", 30))


def h_query(root, a):
    """Read-only SELECT/WITH over the whole environment (its own query_only conn)."""
    sql = a["sql"].strip()
    head = sql.lower().split(None, 1)[0] if sql else ""
    if head not in ("select", "with"):
        raise ValueError("query allows only SELECT / WITH statements")
    con = db.connect(root, read_only=True)
    try:
        return [dict(r) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


# --- tool registry -----------------------------------------------------------
# get_card / review_section land here once Pillars 2 / 8 are built.
def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


_S = {"type": "string"}
_I = {"type": "integer"}
TOOLS = [
    {"name": "status", "description": "Corpus + project state, experiments, and §0 violations.",
     "inputSchema": _obj({"project": _S}), "handler": h_status},
    {"name": "search_corpus", "description": "RAG: retrieve candidate source spans for a query.",
     "inputSchema": _obj({"query": _S, "top_k": _I, "verify": {"type": "boolean"}}, ["query"]),
     "handler": h_search_corpus},
    {"name": "cite_claim", "description": "Anchor + verify a claim to a source span; optionally write to a project.",
     "inputSchema": _obj({"claim": _S, "project": _S, "top_k": _I, "write": {"type": "boolean"}}, ["claim"]),
     "handler": h_cite_claim},
    {"name": "create_project", "description": "Create a project (DB row + workspace dirs).",
     "inputSchema": _obj({"slug": _S, "title": _S}, ["slug"]), "handler": h_create_project},
    {"name": "list_experiments", "description": "The project's experiment DAG with latest metrics.",
     "inputSchema": _obj({"project": _S}, ["project"]), "handler": h_list_experiments},
    {"name": "get_experiment", "description": "One experiment with its runs and metrics.",
     "inputSchema": _obj({"project": _S, "slug": _S}, ["project", "slug"]), "handler": h_get_experiment},
    {"name": "create_experiment", "description": "Create an experiment (optionally under a parent = DAG edge).",
     "inputSchema": _obj({"project": _S, "slug": _S, "title": _S, "hypothesis": _S, "parent": _S},
                         ["project", "slug"]), "handler": h_create_experiment},
    {"name": "run_experiment", "description": "Execute an entrypoint synchronously, recording a reproducible run + metrics.",
     "inputSchema": _obj({"project": _S, "slug": _S, "entrypoint": _S,
                          "params": {"type": "object"}, "dataset": _S, "seed": _I},
                         ["project", "slug", "entrypoint"]), "handler": h_run_experiment},
    {"name": "start_run", "description": "Launch a run in the background (non-blocking); poll with run_status. Use for long runs.",
     "inputSchema": _obj({"project": _S, "slug": _S, "entrypoint": _S,
                          "params": {"type": "object"}, "dataset": _S, "seed": _I,
                          "env_allow": {"type": "array", "items": _S}},
                         ["project", "slug", "entrypoint"]), "handler": h_start_run},
    {"name": "run_status", "description": "Status + metrics of a run (poll a background run started with start_run).",
     "inputSchema": _obj({"run_id": _I}, ["run_id"]), "handler": h_run_status},
    {"name": "log_decision", "description": "Append a typed log entry. A 'result' MUST link a run (§0 invariant); "
                                            "'answers' closes an open question; 'source' records who wrote it.",
     "inputSchema": _obj({"project": _S, "type": {"type": "string", "enum": list(log.ENTRY_TYPES)},
                          "body": _S, "experiment": _S,
                          "runs": {"type": "array", "items": _I},
                          "citations": {"type": "array", "items": _I},
                          "answers": _I, "source": _S},
                         ["project", "type", "body"]), "handler": h_log_decision},
    {"name": "list_log", "description": "Recent decision-log entries with evidence links.",
     "inputSchema": _obj({"project": _S, "limit": _I}, ["project"]), "handler": h_list_log},
    {"name": "check_invariants", "description": "Audit the DB for §0 violations (results with no run).",
     "inputSchema": _obj({}), "handler": h_check_invariants},
    {"name": "add_note", "description": "Add a meeting note to a project.",
     "inputSchema": _obj({"project": _S, "body": _S, "title": _S}, ["project", "body"]),
     "handler": h_add_note},
    {"name": "register_dataset", "description": "Register a versioned, content-hashed evaluation dataset.",
     "inputSchema": _obj({"slug": _S, "version": _S, "path": _S, "description": _S}, ["slug"]),
     "handler": h_register_dataset},
    {"name": "scaffold_project", "description": "Create a project with ideation template + paper skeleton.",
     "inputSchema": _obj({"slug": _S, "title": _S}, ["slug"]), "handler": h_scaffold_project},
    {"name": "weave", "description": "Regenerate results_table.tex + references.bib from the store.",
     "inputSchema": _obj({"project": _S}, ["project"]), "handler": h_weave},
    {"name": "add_paper", "description": "Ingest a paper (PDF path / arXiv id / DOI) into the library + paper table.",
     "inputSchema": _obj({"source": _S, "key": _S, "download": {"type": "boolean"}}, ["source"]),
     "handler": h_add_paper},
    {"name": "list_papers", "description": "List ingested papers with metadata.",
     "inputSchema": _obj({}), "handler": h_list_papers},
    {"name": "discover_papers", "description": "Search arXiv for relevant papers by keyword (literature discovery).",
     "inputSchema": _obj({"query": _S, "limit": _I}, ["query"]), "handler": h_discover_papers},
    {"name": "paper_usage", "description": "Reverse index: where a paper is cited and which log entries use it.",
     "inputSchema": _obj({"key": _S}, ["key"]), "handler": h_paper_usage},
    {"name": "get_card", "description": "A paper's structured card (problem/method/results…); generates if missing.",
     "inputSchema": _obj({"key": _S, "refresh": {"type": "boolean"}}, ["key"]), "handler": h_get_card},
    {"name": "review", "description": "Run automated per-section paper checks; returns findings + a saved report.",
     "inputSchema": _obj({"project": _S}, ["project"]), "handler": h_review},
    {"name": "rubric", "description": "The review rubric (section → checks); the agentic layer runs the llm checks.",
     "inputSchema": _obj({}), "handler": h_rubric},
    {"name": "list_findings", "description": "A project's review findings (optionally filter by status).",
     "inputSchema": _obj({"project": _S, "status": _S}, ["project"]), "handler": h_list_findings},
    {"name": "get_finding", "description": "A finding with its evidence (proof to branch into) + adjudication trail.",
     "inputSchema": _obj({"id": _I}, ["id"]), "handler": h_get_finding},
    {"name": "adjudicate_finding",
     "description": "Accept/reject/defer a finding with reasoning. Rejected findings are never re-raised — "
                    "future agents see the verdict, preventing repeated/hallucinated findings.",
     "inputSchema": _obj({"id": _I, "verdict": {"type": "string", "enum": ["accept", "reject", "defer"]},
                          "reasoning": _S, "by": _S}, ["id", "verdict", "reasoning"]),
     "handler": h_adjudicate_finding},
    {"name": "add_claim", "description": "Add a claim (thesis/contribution/assertion) to the evidence graph.",
     "inputSchema": _obj({"project": _S, "text": _S,
                          "kind": {"type": "string", "enum": ["thesis", "contribution", "assertion"]},
                          "manuscript_loc": _S}, ["project", "text"]), "handler": h_add_claim},
    {"name": "link_claim_evidence", "description": "Attach a citation or run to a claim (supports/refutes); status re-derives.",
     "inputSchema": _obj({"claim_id": _I, "citation_id": _I, "run_id": _I,
                          "stance": {"type": "string", "enum": ["supports", "refutes"]}, "note": _S},
                         ["claim_id"]), "handler": h_link_claim_evidence},
    {"name": "relate_claims", "description": "Chain two claims (depends_on/contradicts) — argument structure, not proof; never changes derived status.",
     "inputSchema": _obj({"claim_id": _I, "related_id": _I,
                          "kind": {"type": "string", "enum": ["depends_on", "contradicts"]},
                          "note": _S},
                         ["claim_id", "related_id"]), "handler": h_relate_claims},
    {"name": "list_claims", "description": "Claims of a project with derived status + evidence counts.",
     "inputSchema": _obj({"project": _S, "status": _S}, ["project"]), "handler": h_list_claims},
    {"name": "get_claim", "description": "A claim with its evidence edges.",
     "inputSchema": _obj({"id": _I}, ["id"]), "handler": h_get_claim},
    {"name": "set_experiment_status", "description": "Set an experiment's status (e.g. abandon a dead branch).",
     "inputSchema": _obj({"project": _S, "slug": _S,
                          "status": {"type": "string", "enum": ["planned", "running", "done", "abandoned"]}},
                         ["project", "slug", "status"]), "handler": h_set_experiment_status},
    {"name": "scan_refs", "description": "All @reref code↔store tags in the tree, each marked resolves/dangling.",
     "inputSchema": _obj({}), "handler": h_scan_refs},
    {"name": "code_refs_for", "description": "Where a store entity (e.g. a finding) is referenced in code — fix locations.",
     "inputSchema": _obj({"kind": _S, "id": _S}, ["kind", "id"]), "handler": h_code_refs_for},
    {"name": "search", "description": "Full-text search the knowledge base (papers, cards, notes, log, claims).",
     "inputSchema": _obj({"query": _S, "project": _S, "limit": _I}, ["query"]), "handler": h_search},
    {"name": "query", "description": "Read-only SQL (SELECT/WITH) over the whole environment.",
     "inputSchema": _obj({"sql": _S}, ["sql"]), "handler": h_query},
]
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


# --- JSON-RPC plumbing -------------------------------------------------------
def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _tool_error(text):
    return {"content": [{"type": "text", "text": text}], "isError": True}


def handle(root, msg):
    """Dispatch one JSON-RPC message. Returns a response dict, or None for notifications."""
    method = msg.get("method")
    mid = msg.get("id")
    if method is None or method.startswith("notifications/"):
        return None  # a response or a notification — nothing to reply
    if method == "initialize":
        params = msg.get("params") or {}
        pv = params.get("protocolVersion") or DEFAULT_PROTOCOL
        return _ok(mid, {"protocolVersion": pv, "capabilities": {"tools": {}},
                         "serverInfo": SERVER_INFO})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")}
                                   for t in TOOLS]})
    if method == "tools/call":
        params = msg.get("params") or {}
        tool = TOOLS_BY_NAME.get(params.get("name"))
        if not tool:
            return _ok(mid, _tool_error(f"unknown tool {params.get('name')!r}"))
        try:
            result = tool["handler"](root, params.get("arguments") or {})
            return _ok(mid, {"content": [{"type": "text",
                                          "text": json.dumps(result, default=str, indent=2)}],
                             "isError": False})
        except Exception as exc:  # surface tool failures to the agent, don't crash
            return _ok(mid, _tool_error(f"{type(exc).__name__}: {exc}"))
    return _err(mid, -32601, f"method not found: {method}")


def serve(root="."):
    """Block reading newline-delimited JSON-RPC from stdin until EOF."""
    _conn(root)  # ensure the DB exists/migrated (cached for the session) before serving
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(root, msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
