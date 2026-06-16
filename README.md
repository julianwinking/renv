# research-env

A **research environment template**: a shared paper library + the `reref` engine
for local, **span-anchored, verified** citations. Clone it once; each paper you
write lives as its own git repo under `projects/`.

Index your library of papers, and when you write a claim get back the **exact
source span** that supports it — anchored as W3C quoted text (not a chunk id),
checked that the span actually supports the claim, and emitted as a LaTeX
`\spancite`.

> **Status & scope.** Per the prior-art scan in [`ideation.md`](ideation.md), the
> research components here already exist (ALCE, LongCite, the "telephone effect"
> paper, citation-accuracy audits). This is a **tool that composes them**, with
> one deliberate design choice — the citation anchor is the *quoted span text*
> (W3C TextQuoteSelector), so it is self-verifying and survives re-indexing and
> new document versions. It is engineering reuse, not a novelty claim.

## Architecture: one shared corpus, many projects

The **engine** (`reref/`) and a single **shared corpus** (`library/` + `.reref/`)
live at the repo root. Each paper you write is a **project** under `projects/`
that retrieves against that one corpus — projects store no PDFs.

```
recursive-referencing/        engine + shared corpus
  reref/  tests/              the engine + tests
  library/                    SHARED references (every paper you've read)  INPUT
  .reref/                     SHARED index + lockfile                      DERIVED
  projects/<paper>/
      ideation.md  src/  text/      your paper (code + LaTeX)
      citations.json                anchored cites for this paper          OUTPUT
```

## Pipeline

```
library/*.pdf ── parse ──> text + char offsets
              ── chunk ──> passages (sentence-level) with offsets
              ── embed ──> vectors ──> shared index + lockfile (.reref/)

claim ── retrieve ──> candidate passages
      ── anchor   ──> W3C TextQuote + TextPosition selectors (version-robust)
      ── verify   ──> does the span support the claim?  (full / partial / none)
      ── cite     ──> \spancite{src}{start}{end}{quote} + <project>/citations.json
```

## Quickstart (zero dependencies)

The default stack is **stdlib-only** so it runs today on Python 3.14.

```bash
# 1. put .txt/.md/.pdf papers in library/  (two demo papers are included)
python3 -m reref.cli index                           # index the shared corpus
python3 -m reref.cli status projects/span-citation   # corpus + project state

# 2. cite the corpus from a project
python3 -m reref.cli cite "Citation precision uses NLI to flag unsupported passages." projects/span-citation --all
python3 -m reref.cli cite "..." projects/span-citation --write   # -> projects/span-citation/citations.json

python3 -m reref.cli resolve "smaller passages are easier to verify"
python3 -m reref.cli preamble                         # LaTeX \spancite macro
python3 tests/test_selectors.py && python3 tests/test_pipeline.py
```

Point `--corpus PATH` at a different corpus root to keep separate libraries.

## The lockfile (consistency / hand-off)

`.reref/reref.lock.json` pins parser, chunker, embedder + versions, and a
**sha256 per source file**. Hand the corpus to a collaborator and they reproduce
an identical index. Each emitted citation additionally records the cited source's
`source_sha256` + the **quoted text**, so a finished paper's citations keep
resolving even as the shared library grows or files are re-versioned — the anchor
never depends on a chunk/vector id.

## SOTA backends (drop-in upgrades)

Default backends are lightweight; the verified SOTA picks are pluggable adapters
(lazy-imported). All listed options are commercially-permissive (see
`ideation.md` for the license audit).

| Layer | Default (now) | SOTA upgrade |
|---|---|---|
| PDF parse | `pdfminer.six` (MIT) | **Docling** (MIT, `page_no`+`bbox`+`charspan`) |
| Embeddings | builtin TF-IDF | **Qwen3-Embedding-0.6B** / **BGE-M3** (Apache/MIT) |
| Span citation | retrieve + anchor | **LongCite-llama3.1-8b** (one-pass sentence cites) |
| Verify support | lexical overlap | **FactCG-DeBERTa-v3** (MIT) |
| Re-anchor | stdlib `difflib` | **RapidFuzz** (MIT) |

```bash
pip install -e ".[pdf,anchor]"           # light, recommended
pip install -e ".[parse-sota,embed-local,verify-local]"   # full SOTA (needs torch)
```

## Layout

```
reref/      the engine (indexing, retrieval, anchoring, verification)
tests/      dependency-free unit + integration tests
library/    SHARED corpus of reference papers (index once)
.reref/     shared index + lockfile (derived)
projects/   one folder per paper: ideation.md, src/, text/, citations.json
```
