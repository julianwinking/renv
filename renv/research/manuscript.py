"""Manuscript files under ``projects/<slug>/text/`` — the Overleaf-shaped write surface.

The paper itself is a tree of LaTeX (and weave outputs) on disk; citations and
numbers still enter only through the store (``\\spancite`` rows, ``metric`` rows
via ``renv weave``). This module is the domain for listing/reading/writing that
tree, compiling it to PDF, and retrieving span-anchored citations against the
corpus index. CLI, MCP, and the cockpit are thin shells over these functions.

Why not an in-browser WASM TeX engine (SwiftLaTeX, BusyTeX, WasmTeX)?
KaTeX/MathJax/latex.js cannot compile a real paper (``\\input``, ``booktabs``,
``\\bibliography``). WASM pdfTeX ports can, but they ship a TeX Live tree of
hundreds of MB, which violates the lean-core rule (one small pure-Python
dependency; heavy backends are optional extras). So compilation is an *optional
local engine* — ``latexmk``, ``tectonic``, or ``pdflatex`` on PATH — and the
cockpit previews with PDF.js (already used by the Papers reader). No engine
still lets you edit, weave, and insert ``\\spancite``; the PDF pane just says
so.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

from renv.research import synctex
from renv.research.db import project_id, row_to_dict

GENERATED_NAMES = frozenset({"results_table.tex", "references.bib"})
ENGINE_OWNED = frozenset({"preamble.tex"})
PROTECTED_NAMES = frozenset({"paper.tex"}) | GENERATED_NAMES | ENGINE_OWNED
WRITE_SUFFIXES = frozenset({".tex", ".bib", ".sty", ".cls", ".txt", ".md", ".cfg"})
BUILD_SUFFIXES = frozenset({
    ".aux", ".log", ".out", ".bbl", ".blg", ".toc", ".lof", ".lot",
    ".fls", ".fdb_latexmk", ".synctex.gz",
})
MAX_BYTES = 2 * 1024 * 1024
COMPILE_TIMEOUT = 120

_SPANCITE = re.compile(
    r"\\spancite\{(?P<source>[^}]*)\}"
    r"\{(?P<start>\d+)\}"
    r"\{(?P<end>\d+)\}"
    r"\{(?P<quote>[^}]*)\}"
)
_CITE = re.compile(r"\\cite[tp]?\{([^}]+)\}")
_INPUT = re.compile(r"\\(?:input|include)\{([^}]+)\}")


# --- path sandbox -------------------------------------------------------------
def _project_root(corpus_root, slug: str) -> Path:
    return Path(corpus_root) / "projects" / slug


def _text_root(corpus_root, slug: str) -> Path:
    text = (_project_root(corpus_root, slug) / "text").resolve()
    text.mkdir(parents=True, exist_ok=True)
    return text


def _safe_file(text: Path, rel: str) -> Path:
    """Resolve ``rel`` inside ``text/``; refuse absolute paths and ``..``."""
    if not rel or not str(rel).strip():
        raise ValueError("path is required")
    raw = str(rel).replace("\\", "/")
    candidate = Path(raw)
    if candidate.is_absolute() or raw.startswith("/") or raw.startswith("~") \
            or any(part == ".." for part in candidate.parts):
        raise ValueError("path escapes text/")
    rel = raw.lstrip("/")
    p = Path(rel)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        raise ValueError("path escapes text/")
    target = (text / p).resolve()
    try:
        target.relative_to(text)
    except ValueError as exc:
        raise ValueError("path escapes text/") from exc
    return target


def _is_generated(name: str) -> bool:
    return name in GENERATED_NAMES


def _writable(name: str, kind: str = "file") -> bool:
    if kind != "file":
        return False
    suf = Path(name).suffix.lower()
    if suf == ".pdf" or suf in BUILD_SUFFIXES:
        return False
    if name in GENERATED_NAMES or name in ENGINE_OWNED:
        return False
    return suf in WRITE_SUFFIXES


# --- tree / read / write ------------------------------------------------------
def list_tree(con: sqlite3.Connection, corpus_root, slug: str) -> dict:
    """Nested file tree of ``text/``. Build cruft is omitted; weave outputs flagged."""
    project_id(con, slug)
    text = _text_root(corpus_root, slug)
    return {"slug": slug, "root": "text", "tree": _walk(text, text),
            "main": "paper.tex" if (text / "paper.tex").exists() else None,
            "pdf": (text / "paper.pdf").is_file()}


def _walk(text: Path, here: Path) -> list[dict]:
    out = []
    try:
        entries = sorted(here.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except FileNotFoundError:
        return out
    for p in entries:
        if p.name.startswith("."):
            continue
        suf = "".join(p.suffixes).lower() if p.is_file() else ""
        if p.is_file() and (p.suffix.lower() in BUILD_SUFFIXES or suf.endswith(".synctex.gz")):
            continue
        rel = p.relative_to(text).as_posix()
        if p.is_dir():
            out.append({"path": rel, "name": p.name, "kind": "dir",
                        "children": _walk(text, p)})
        else:
            out.append({"path": rel, "name": p.name, "kind": "file",
                        "bytes": p.stat().st_size,
                        "generated": _is_generated(p.name),
                        "engine_owned": p.name in ENGINE_OWNED,
                        "writable": _writable(p.name),
                        "build": p.suffix.lower() == ".pdf"})
    return out


def read_file(con: sqlite3.Connection, corpus_root, slug: str, rel: str) -> dict:
    project_id(con, slug)
    path = _safe_file(_text_root(corpus_root, slug), rel)
    if not path.is_file():
        raise KeyError(f"no file text/{rel}")
    if path.suffix.lower() == ".pdf" or path.suffix.lower() in BUILD_SUFFIXES:
        raise ValueError(f"{rel} is a build artifact — not editable text")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"{rel} is larger than {MAX_BYTES} bytes")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{rel} is not UTF-8 text") from exc
    return {"path": rel, "content": content, "bytes": len(data),
            "generated": _is_generated(path.name),
            "engine_owned": path.name in ENGINE_OWNED,
            "writable": _writable(path.name)}


def write_file(con: sqlite3.Connection, corpus_root, slug: str, rel: str,
               content: str) -> dict:
    """Create or overwrite a text file under ``text/``. Weave outputs are refused."""
    project_id(con, slug)
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError(f"file too large ({len(data)} > {MAX_BYTES} bytes)")
    path = _safe_file(_text_root(corpus_root, slug), rel)
    if path.name in ENGINE_OWNED:
        raise ValueError(
            f"{path.name} is engine-owned — put packages in paper.tex, not here")
    if _is_generated(path.name):
        raise ValueError(
            f"{path.name} is generated by `renv weave` — edit the store, then weave")
    if path.suffix.lower() not in WRITE_SUFFIXES:
        raise ValueError(f"refusing to write {path.suffix or 'extensionless'} "
                         f"(allowed: {', '.join(sorted(WRITE_SUFFIXES))})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"saved": rel, "bytes": len(data)}


def delete_file(con: sqlite3.Connection, corpus_root, slug: str, rel: str) -> dict:
    """Remove a user file. Skeleton + weave outputs stay."""
    project_id(con, slug)
    path = _safe_file(_text_root(corpus_root, slug), rel)
    if path.name in PROTECTED_NAMES:
        raise ValueError(f"{path.name} is part of the paper skeleton — not deleted")
    if not path.exists():
        raise KeyError(f"no file text/{rel}")
    if path.is_dir():
        raise ValueError("refusing to delete a directory")
    path.unlink()
    return {"deleted": rel}


# --- LaTeX scan ---------------------------------------------------------------
def parse_tex_macros(tex: str, *, path: str = "paper.tex") -> dict:
    """Pull ``\\spancite``, ``\\cite``, and ``\\input``/``\\include`` sites out of one file."""
    def _line(offset: int) -> int:
        return tex.count("\n", 0, offset) + 1

    spancites = [{
        "path": path, "source_id": m.group("source"), "start": int(m.group("start")),
        "end": int(m.group("end")), "quote": m.group("quote"),
        "offset": m.start(), "length": m.end() - m.start(),
        "line": _line(m.start()),
    } for m in _SPANCITE.finditer(tex)]
    cites: list[dict] = []
    for m in _CITE.finditer(tex):
        for key in (k.strip() for k in m.group(1).split(",") if k.strip()):
            cites.append({"path": path, "key": key, "offset": m.start(),
                          "line": _line(m.start())})
    inputs = [{"path": path, "name": m.group(1), "offset": m.start(),
               "line": _line(m.start())}
              for m in _INPUT.finditer(tex)]
    return {"spancites": spancites, "cites": cites, "inputs": inputs}


def _as_tex_rel(name: str) -> str:
    n = str(name or "").strip().replace("\\", "/").lstrip("/")
    if not n:
        return ""
    return n if n.endswith(".tex") else f"{n}.tex"


def _walk_tex_macros(text: Path, rel: str, seen: set[str], acc: dict) -> None:
    """Expand ``\\input``/``\\include`` inline (typeset order) and collect macros."""
    rel = _as_tex_rel(rel)
    if not rel or rel in seen:
        return
    try:
        path = _safe_file(text, rel)
    except ValueError:
        return
    if not path.is_file():
        return
    rel = path.relative_to(text).as_posix()
    if rel in seen:
        return
    seen.add(rel)
    parsed = parse_tex_macros(
        path.read_text(encoding="utf-8", errors="replace"), path=rel)
    events = (
        [(s["offset"], 0, "spancite", s) for s in parsed["spancites"]]
        + [(c["offset"], 1, "cite", c) for c in parsed["cites"]]
        + [(i["offset"], 2, "input", i) for i in parsed["inputs"]]
    )
    events.sort(key=lambda e: (e[0], e[1]))
    acc["inputs"].extend(parsed["inputs"])
    for _, _, kind, obj in events:
        if kind == "input":
            _walk_tex_macros(text, obj["name"], seen, acc)
        elif kind == "spancite":
            acc["spancites"].append(obj)
        else:
            acc["cites"].append(obj)


def scan_tree(con: sqlite3.Connection, corpus_root, slug: str) -> dict:
    """Parse ``.tex`` files in typeset order (``paper.tex`` ``\\input`` walk), then orphans."""
    project_id(con, slug)
    text = _text_root(corpus_root, slug)
    acc: dict = {"spancites": [], "cites": [], "inputs": []}
    typeset: set[str] = set()
    if (text / "paper.tex").is_file():
        _walk_tex_macros(text, "paper.tex", typeset, acc)
    seen = set(typeset)
    for p in sorted(text.rglob("*.tex")):
        rel = p.relative_to(text).as_posix()
        if rel not in seen:
            _walk_tex_macros(text, rel, seen, acc)
    return {**acc, "typeset_files": sorted(typeset)}


# --- compile ------------------------------------------------------------------
def detect_engine(which=shutil.which) -> dict | None:
    """First usable TeX engine on PATH. None if the machine has no compiler."""
    if which("latexmk"):
        return {"name": "latexmk", "path": which("latexmk")}
    if which("tectonic"):
        return {"name": "tectonic", "path": which("tectonic")}
    if which("pdflatex"):
        return {"name": "pdflatex", "path": which("pdflatex")}
    return None


def _commands(engine: str, main: str) -> list[list[str]]:
    if engine == "latexmk":
        return [["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode",
                 "-halt-on-error", "-file-line-error", "-no-shell-escape", main]]
    if engine == "tectonic":
        return [["tectonic", "-Z", "synctex", main]]
    if engine == "pdflatex":
        stem = Path(main).stem
        tex = ["pdflatex", "-synctex=1", "-interaction=nonstopmode",
               "-halt-on-error", "-no-shell-escape", main]
        return [tex, ["bibtex", stem], tex, tex]
    raise ValueError(f"unknown engine {engine!r}")


def _latex_errors(log: str) -> list[str]:
    lines = []
    for line in (log or "").splitlines():
        if line.startswith("!") or re.match(r"^.+:\d+: ", line):
            lines.append(line[:240])
        if len(lines) >= 40:
            break
    return lines


def compile_pdf(text_dir: Path, *, main: str = "paper.tex", engine: dict | None = None,
                timeout: int = COMPILE_TIMEOUT) -> dict:
    """Run a TeX engine in ``text_dir``. ``engine`` may be injected by tests."""
    text_dir = Path(text_dir)
    main_path = _safe_file(text_dir.resolve(), main)
    if main_path.suffix.lower() != ".tex":
        raise ValueError("main file must be .tex")
    if not main_path.is_file():
        raise KeyError(f"no file text/{main}")
    rel_main = main_path.relative_to(text_dir.resolve()).as_posix()
    eng = engine or detect_engine()
    if not eng:
        return {
            "ok": False, "engine": None, "pdf": False,
            "log": "", "errors": [],
            "tried": ["latexmk", "tectonic", "pdflatex"],
            "hint": "Install TeX Live (latexmk) or tectonic to compile. "
                    "Editing, weave, and \\spancite still work without it.",
        }
    commands = eng.get("commands") or _commands(eng["name"], rel_main)
    chunks: list[str] = []
    code = 0
    for cmd in commands:
        # bibtex is allowed to fail (no \citation yet); pdflatex/latexmk are not
        try:
            proc = subprocess.run(
                cmd, cwd=str(text_dir), capture_output=True, text=True,
                timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "engine": eng["name"], "pdf": False,
                    "log": "\n".join(chunks) + f"\n! timeout after {timeout}s",
                    "errors": [f"compile timed out after {timeout}s"],
                    "hint": None}
        except FileNotFoundError:
            return {"ok": False, "engine": eng["name"], "pdf": False,
                    "log": "\n".join(chunks),
                    "errors": [f"engine binary missing: {cmd[0]}"],
                    "hint": None}
        chunk = (proc.stdout or "") + (proc.stderr or "")
        chunks.append(chunk)
        if proc.returncode and Path(cmd[0]).name != "bibtex":
            code = proc.returncode
            break
    log = "\n".join(chunks)
    pdf = main_path.with_suffix(".pdf")
    ok = pdf.is_file() and code == 0
    return {
        "ok": ok, "engine": eng["name"], "pdf": pdf.is_file(),
        "log": log[-80_000:], "errors": _latex_errors(log),
        "hint": None if ok else "see log",
        "code": code,
    }


def compile_manuscript(con: sqlite3.Connection, corpus_root, slug: str, *,
                       main: str = "paper.tex", weave: bool = True,
                       engine: dict | None = None,
                       timeout: int = COMPILE_TIMEOUT) -> dict:
    """Weave (numbers + bib from the store) then compile. One cockpit 'Recompile'."""
    from renv.research import authoring
    project_id(con, slug)
    proot = _project_root(corpus_root, slug)
    authoring.write_preamble(proot)
    woven = []
    if weave:
        woven = [p.name for p in authoring.weave(con, slug, proot)]
    result = compile_pdf(_text_root(corpus_root, slug), main=main,
                         engine=engine, timeout=timeout)
    result["woven"] = woven
    result["slug"] = slug
    result["main"] = main
    return result


def pdf_bytes(con: sqlite3.Connection, corpus_root, slug: str,
              main: str = "paper.tex") -> bytes:
    project_id(con, slug)
    pdf = _safe_file(_text_root(corpus_root, slug),
                     str(Path(main).with_suffix(".pdf")))
    if not pdf.is_file():
        raise KeyError("no compiled PDF — run compile first")
    return pdf.read_bytes()


# --- writing context (citations + metrics + papers, for the cockpit palette) --
def writing_context(con: sqlite3.Connection, corpus_root, slug: str) -> dict:
    """Everything the Write view needs besides the file tree: store-backed
    citations, parsed ``\\spancite`` sites, experiment metrics, claim texts,
    corpus papers, and whether a TeX engine is installed."""
    from renv.papers import ingest
    from renv.research import claim as claimmod
    from renv.research import experiment as expmod

    project_id(con, slug)
    scan = scan_tree(con, corpus_root, slug)
    rows = ingest.citations_for_project(con, slug)
    by_span = {(r["source_id"], r["src_start"]): r for r in rows}
    for s in scan["spancites"]:
        hit = by_span.get((s["source_id"], s["start"]))
        s["citation_id"] = hit["id"] if hit else None
        s["support"] = hit["support"] if hit else None
        s["in_store"] = hit is not None
    metrics = []
    for e in expmod.list_experiments(con, slug):
        for name, value in (e.get("metrics") or {}).items():
            metrics.append({"experiment": e["slug"], "name": name, "value": value,
                            "run_id": None})
    papers = [{"id": p["id"], "key": p["key"], "title": p["title"], "year": p["year"]}
              for p in ingest.list_papers(con)]
    claims = [{"id": c["id"], "kind": c["kind"], "status": c["status"],
               "text": c["text"]} for c in claimmod.list_claims(con, slug)]
    text = _text_root(corpus_root, slug)
    eng = detect_engine()
    used = usage(con, corpus_root, slug)
    return {
        "slug": slug,
        "engine": ({"name": eng["name"], "path": eng["path"]} if eng else None),
        "pdf": (text / "paper.pdf").is_file(),
        "synctex": synctex.synctex_path(text).is_file(),
        "citations": [row_to_dict(r) if not isinstance(r, dict) else r for r in rows],
        "spancites": scan["spancites"],
        "cites": scan["cites"],
        "inputs": scan["inputs"],
        "metrics": metrics,
        "claims": claims,
        "papers": papers,
        "generated": sorted(GENERATED_NAMES),
        "usage": used,
    }


# --- span citation (same path as `renv cite` / MCP cite_claim) ----------------
def cite_claim(con: sqlite3.Connection, corpus_root, claim: str, *,
               project: str | None = None, source: str | None = None,
               write: bool = False, force: bool = False,
               verifier: str = "lexical", top_k: int = 5,
               manuscript_loc: str | None = None, pick: int = 0) -> dict:
    """Retrieve + verify a span against the corpus index; optionally record it.

    A ``support='none'`` verdict is not written unless ``force``. The returned
    ``latex`` is a ``\\spancite{key}{start}{end}{quote}`` — never a bare
    ``\\cite{key}``.
    """
    from renv.corpus.cite import append_sidecar, make_citation
    from renv.papers import ingest
    from renv.project import Corpus, Project

    claim = (claim or "").strip()
    if not claim:
        raise ValueError("claim is required")
    corpus = Corpus(corpus_root)
    try:
        retriever, lock = corpus.retriever(verifier)
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    hashes = {s.source_id: s.sha256 for s in lock.sources}
    if source and not any(s.source_id == source for s in lock.sources):
        raise KeyError(f"source {source!r} is not an indexed source "
                       "(check `renv papers` / `renv status`, then `renv index`)")
    cands = retriever.search(claim, top_k=top_k, verify=True, source_id=source)
    if not cands:
        return {"found": False, "source": source, "candidates": []}

    def payload(c):
        cit = make_citation(claim, c, hashes.get(c.record.source_id, ""))
        return {**cit.to_dict(), "latex": cit.latex(), "page": cit.page}

    candidates = [payload(c) for c in cands]
    pick = max(0, min(int(pick), len(cands) - 1))
    best = cands[pick]
    cit = make_citation(claim, best, hashes.get(best.record.source_id, ""))
    result = {"found": True, **cit.to_dict(), "latex": cit.latex(),
              "candidates": candidates, "written": False, "pick": pick}
    if not write:
        return result
    if not project:
        raise ValueError("project is required to write a citation")
    if cit.support == "none" and not force:
        result["reason"] = (
            "verifier verdict is 'none' — the span does not support the claim; "
            "reword closer to the source, pin `source`, or pass force=true")
        return result
    proj = Project(_project_root(corpus_root, project))
    try:
        project_id(con, project)
        row = ingest.record_citation(con, project, cit, manuscript_loc=manuscript_loc)
        result["citation_id"] = row["id"]
        result["paper_id"] = row["paper_id"]
        result["sidecar"] = str(ingest.regenerate_sidecar(con, project, proj.root))
        result["written"] = True
    except KeyError:
        proj.ensure()
        result["sidecar"] = str(append_sidecar(proj.root, cit,
                                               filename=proj.citations_path.name))
        result["written"] = True
        result["store"] = False
    return result


def usage(con: sqlite3.Connection, corpus_root, slug: str) -> dict:
    """Papers and experiments actually referenced from the manuscript.

    Papers: unique ``\\spancite`` keys in first-appearance (typeset) order —
    the numbers the PDF hover card shows, matching ``\\spn@assign``. Bare
    ``\\cite`` keys are still listed in ``papers`` (graph "In paper") but do
    not get a ``cite_numbers`` slot: the preamble counter only steps on
    ``\\spancite``. Experiments: those whose metrics land in
    ``results_table.tex`` *and* that table is ``\\input`` from a ``.tex``
    file — the weave-to-paper path, not every experiment in the DAG.
    """
    from renv.research import experiment as expmod
    scan = scan_tree(con, corpus_root, slug)
    typeset = set(scan.get("typeset_files") or [])
    span_keys: list[str] = []
    papers: list[str] = []
    seen: set[str] = set()
    for s in scan["spancites"]:
        key = (s.get("source_id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        papers.append(key)
        # PDF [n] only for macros that actually typeset from paper.tex.
        if not typeset or s.get("path") in typeset:
            span_keys.append(key)
    for c in scan["cites"]:
        key = (c.get("key") or "").strip()
        if key and key not in seen:
            seen.add(key)
            papers.append(key)
    cites_results = any(
        Path(str(i.get("name") or "")).stem == "results_table"
        for i in scan["inputs"])
    experiments = []
    if cites_results:
        experiments = [
            r["slug"] for r in expmod.list_experiments(con, slug)
            if r.get("metrics")
        ]
    return {
        "papers": papers,
        "experiments": experiments,
        "cite_numbers": {k: i + 1 for i, k in enumerate(span_keys)},
        "results_table": cites_results,
    }


def _finish_sync(text_dir: Path, hit: dict, via: str) -> dict:
    out = {k: v for k, v in hit.items()}
    out["ok"] = True
    out["via"] = hit.get("engine") or via
    if out.get("path"):
        out["path"] = synctex.rel_path(text_dir, str(out["path"]))
    return out


def _inside_text(text_dir: Path, rel: str, default: str | None = None) -> str | None:
    """Resolve ``rel`` inside ``text_dir``; ``default`` (or None) if it escapes."""
    try:
        return _safe_file(text_dir, rel).relative_to(text_dir).as_posix()
    except ValueError:
        return default


def sync_from_tex(text_dir: Path, rel: str, line: int, text: str | None = None,
                  main: str = "paper.tex") -> dict:
    """Forward SyncTeX: editor line → PDF page/x/y. Falls back to a text hint."""
    text_dir = Path(text_dir).resolve()
    rel = _inside_text(text_dir, rel) or "paper.tex"
    main = _inside_text(text_dir, main or "paper.tex", "paper.tex") or "paper.tex"
    hit = synctex.view_cli(text_dir, rel, int(line), main=main) \
        or synctex.view(text_dir, rel, int(line), main=main)
    if hit:
        return _finish_sync(text_dir, hit, "synctex")
    return {"ok": False, "fallback": "text", "path": rel,
            "line": int(line), "text": (text or "").strip()[:240]}


def sync_from_pdf(text_dir: Path, page: int, x: float, y: float,
                  snippet: str | None = None, prefer: str | None = None,
                  main: str = "paper.tex") -> dict:
    """Inverse SyncTeX: PDF click → source file/line. Text-search fallback."""
    text_dir = Path(text_dir).resolve()
    main = _inside_text(text_dir, main or "paper.tex", "paper.tex") or "paper.tex"
    if prefer:
        prefer = _inside_text(text_dir, prefer)
    hit = synctex.edit_cli(text_dir, int(page), float(x), float(y), main=main) \
        or synctex.edit(text_dir, int(page), float(x), float(y), main=main)
    if hit:
        return _finish_sync(text_dir, hit, "synctex")
    if snippet:
        found = synctex.locate_snippet(text_dir, snippet, prefer=prefer)
        if found:
            return {**found, "via": found.get("engine") or "text"}
    return {"ok": False, "reason": "no-synctex"}
