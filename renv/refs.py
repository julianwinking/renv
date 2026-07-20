"""Code ↔ research-store cross-references — a comment tag linking code to origins.

A distinct, greppable tag lets code point at the paper, finding, decision, run, or
claim it came from, so:
  • an agent (or you) reading the code pulls the originating research context;
  • the dashboard sees *where* a finding was fixed (finding → file:line);
  • on publication a strip pass removes the internal tags.

Tag format (in any comment):

    @renv:<kind>:<id>[:<relation>] [free text]

  kind ∈ paper | finding | decision | run | claim | dataset | experiment
  id   = the store id (integer) or key (e.g. a paper key / experiment slug)
  relation (optional) = fixes | implements | per | refutes | ...   (free-form verb)

Examples:
    # @renv:finding:42:fixes  guard malformed metrics.json (review HIGH)
    # @renv:paper:gao2023_alce:implements  ALCE citation-precision metric
    # @renv:decision:17  per the sentence-anchor decision
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

KINDS = ("paper", "finding", "decision", "run", "claim", "dataset", "experiment")
TAG_RE = re.compile(
    r"@renv:(?P<kind>paper|finding|decision|run|claim|dataset|experiment)"
    r":(?P<id>[\w./-]+)(?::(?P<relation>[\w-]+))?(?:[ \t]+(?P<text>[^\n]*))?"
)
_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".renv", ".research",
              "node_modules", ".pytest_cache", "build", "dist"}
_EXTS = {".py", ".md", ".tex", ".txt", ".toml", ".cfg", ".sh", ".js", ".ts"}


def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in _EXTS and not (_SKIP_DIRS & set(p.parts)):
            yield p


def scan(root=".") -> list[dict]:
    """Find every @renv tag in the tree. Returns file/line-located references."""
    root = Path(root)
    out = []
    for path in _iter_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            for m in TAG_RE.finditer(line):
                out.append({
                    "file": str(path.relative_to(root)), "line": n,
                    "kind": m.group("kind"), "id": m.group("id"),
                    "relation": m.group("relation"),
                    "text": (m.group("text") or "").strip(),
                })
    return out


# --- validation against the store -------------------------------------------
def _exists(con: sqlite3.Connection, kind: str, ident: str) -> bool:
    table, col = {
        "paper": ("paper", "key"), "finding": ("finding", "id"),
        "decision": ("log_entry", "id"), "run": ("run", "id"),
        "claim": ("claim", "id"), "dataset": ("dataset", "slug"),
        "experiment": ("experiment", "slug"),
    }[kind]
    return con.execute(
        f"SELECT 1 FROM {table} WHERE {col}=? LIMIT 1", (ident,)).fetchone() is not None


def validate(con: sqlite3.Connection, refs: list[dict]) -> list[dict]:
    """Annotate each ref with whether its target exists in the store (dangling refs)."""
    for r in refs:
        r["resolves"] = _exists(con, r["kind"], r["id"])
    return refs


def code_refs_for(con: sqlite3.Connection, root, kind: str, ident: str) -> list[dict]:
    """Where in the code a given store entity is referenced (e.g. where a finding was fixed)."""
    return [r for r in scan(root) if r["kind"] == kind and r["id"] == str(ident)]


# --- publication strip -------------------------------------------------------
def strip_text(text: str) -> str:
    """Remove @renv tags; drop comment lines that become empty as a result."""
    out = []
    for line in text.splitlines(keepends=False):
        new = TAG_RE.sub("", line)
        if new != line:
            stripped = new.rstrip()
            # if the line is now an empty comment, drop it entirely
            if stripped.lstrip() in ("#", "//", "%", "*", "<!--", ""):
                continue
            new = stripped
        out.append(new)
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + trailing


def strip_path(path: Path, *, in_place: bool = False) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    cleaned = strip_text(text)
    if in_place and cleaned != text:
        Path(path).write_text(cleaned)
    return cleaned
