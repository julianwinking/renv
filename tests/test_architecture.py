"""The package layering, enforced — a structure only documented is a structure
that drifts. Rules checked here:

  1. `corpus` (the retrieval pipeline) is pure: it may import only itself and
     the config kernel — never the research store, papers, or any client.
  2. No domain package imports a client shell (cli / web / mcp_server); the
     dependency arrow points shell -> domain, never back.
  3. `sqlite3.connect` happens in exactly one module: renv/research/db.py.
     Every other module goes through a domain function ("one store, thin
     clients" as a failing test instead of a sentence in AGENTS.md).
"""

from __future__ import annotations

import ast
from pathlib import Path

RENV = Path(__file__).resolve().parent.parent / "renv"
CLIENTS = {"renv.cli", "renv.web", "renv.mcp_server"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def _package_files(pkg: str):
    return sorted((RENV / pkg).glob("*.py"))


def test_corpus_is_pure():
    allowed = ("renv.corpus", "renv.config")
    for f in _package_files("corpus"):
        bad = [m for m in _imports(f) if m.startswith("renv") and
               not m.startswith(allowed)]
        assert not bad, f"{f.name} imports outside the pipeline: {bad}"


def test_domain_never_imports_clients():
    for pkg in ("corpus", "papers", "research"):
        for f in _package_files(pkg):
            bad = [m for m in _imports(f) if m in CLIENTS]
            assert not bad, f"{pkg}/{f.name} imports a client shell: {bad}"


def test_sqlite_connect_only_in_db():
    for f in RENV.rglob("*.py"):
        if f.relative_to(RENV).as_posix() == "research/db.py":
            continue
        src = f.read_text()
        assert "sqlite3.connect" not in src, (
            f"{f.relative_to(RENV)} opens SQLite directly — go through "
            "renv.research.db (one store, thin clients)")
