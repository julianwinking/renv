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

## Quickstart (uv)

The project is managed with [uv](https://docs.astral.sh/uv/). The default stack is
**stdlib-only** (the heavy SOTA backends are optional extras), so one `uv sync`
gives you a working environment on Python 3.14 with nothing to compile.

```bash
uv sync                                      # create .venv + install (pins Python 3.14)

# 1. put .txt/.md/.pdf papers in library/  (two demo papers are included)
uv run reref index                           # index the shared corpus
uv run reref status projects/span-citation   # corpus + project state

# 2. cite the corpus from a project
uv run reref cite "Citation precision uses NLI to flag unsupported passages." projects/span-citation --all
uv run reref cite "..." projects/span-citation --write   # -> projects/span-citation/citations.json

uv run reref resolve "smaller passages are easier to verify"
uv run reref preamble                         # LaTeX \spancite macro
uv run pytest                                 # run the test suite
```

`uv run reref` invokes the `reref` console script; `uv run python -m reref.cli`
works too. Point `--corpus PATH` at a different corpus root to keep separate
libraries.

## Experiments + reasoning log (the research store)

Beyond citations, the environment tracks **what you did, in what order, and why**
in one central SQLite DB (`.research/env.db`, stdlib `sqlite3`, no new dep) — the
single ground truth, with the `reref` CLI, an MCP server, and a web cockpit as
clients over it. See [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) for the full design.

```bash
uv run reref db init                          # create/migrate the env DB
uv run reref project new span-citation        # DB row + workspace dirs

# experiments form a DAG (one experiment, one question)
uv run reref exp new span-citation 001-tfidf --title "TF-IDF baseline"
uv run reref exp new span-citation 002-dense --parent 001-tfidf

# runs are reproducible: the entrypoint reads REREF_RUN_DIR + REREF_PARAMS and
# writes metrics.json; we pin git sha, env hash, dataset, config hash, seed.
uv run reref dataset add alce-claims --path library/gao2023_alce.txt
uv run reref exp run span-citation 001-tfidf --entrypoint run.py --param k=8 --dataset alce-claims
uv run reref exp list span-citation           # the progress view (DAG + metrics)

# the decision log — numbers may only enter via a recorded run
uv run reref log add span-citation result "recall hit 0.8" --evidence run:1
uv run reref log add span-citation decision "Anchor at sentence granularity"
uv run reref log check                         # audit the §0 invariant
uv run reref export                            # deterministic JSONL snapshot for git
```

**Provenance enforcement (not a correctness proof):** a `result` log entry is
*rejected* unless it links a *done* run of the same project, and `reref log check`
re-audits the whole DB — so a measured number can't be asserted without a recorded
run behind it. This guarantees provenance, not validity: a buggy run can still
produce a wrong number. See `docs/BLUEPRINT.md` → *Honest status* for what is and
isn't guaranteed.

## Discover & search

```bash
uv run reref discover "span-level citation faithfulness" --add 0   # arXiv search → ingest result 0
uv run reref search "sentence anchoring"                           # FTS over papers/cards/notes/log/claims
uv run reref export --project span-citation     # project-scoped JSONL slice
uv run reref import                              # rebuild the DB from the export (round-trip)
```

Long experiments run in the background so they never block an agent:
`start_run` + `run_status` (MCP), and the runner withholds secret-named env vars by
default (`reref exp run … --env-allow OPENAI_API_KEY` to opt one in).

## Draft the paper (numbers generated, never typed)

```bash
uv run reref new span-citation --title "Span-anchored citation"  # ideation.md + text/ skeleton
# ... run experiments (above) ...
uv run reref weave span-citation        # regenerate results_table.tex + references.bib
```

`reref new` scaffolds `ideation.md` (a structured plan with a prior-art positioning
table) and a LaTeX skeleton (`paper.tex` + the `\spancite` preamble). `reref weave`
regenerates `text/results_table.tex` straight from the `metric` rows and
`text/references.bib` from cited papers — so the paper's numbers and bibliography
are build outputs of the store, never hand-typed text that can drift.

## The claim/evidence graph

Assertions are first-class and traced to evidence — the backbone that makes "every
claim is backed" checkable:

```bash
uv run reref claim add span-citation "Span anchoring beats paper-level citation" --kind thesis
uv run reref claim link 1 --cite 3 --stance supports     # a verified citation backs it
uv run reref claim link 1 --run 7  --stance refutes       # a run that contradicts it
uv run reref claim list span-citation                     # status is DERIVED from evidence
```

A claim's status (`open` / `supported` / `refuted`) is computed from its evidence,
not hand-set. `reref review` flags any thesis/contribution claim still `open`.

## The web cockpit

```bash
uv run reref web                 # → http://127.0.0.1:8765
```

There are two frontends over the same JSON API (the store is the single source of
truth either way; every edit goes through the same domain functions as CLI/MCP):

- **Buildless page** (default, stdlib, zero toolchain): dashboard, papers +
  **citation usage map**, branch explorer, findings with accept/reject, claim graph,
  timeline + notes.
- **React Flow graph app** (`cockpit/`, richer): experiment branches, claims,
  findings, citations, and papers as connected, **expandable interactive nodes** on
  a dagre-laid-out canvas — inline finding accept/reject, claim→evidence edges.
  Build it and `reref web` serves it automatically:
  ```bash
  cd cockpit && npm install && npm run build   # → cockpit/dist
  uv run reref web                              # now serves the graph app
  ```
  For live development: `npm run dev` (Vite at :5173, proxies to the API). See
  [`cockpit/README.md`](cockpit/README.md).

## Drive it from Claude Code (MCP)

`.mcp.json` registers a local stdio MCP server (`reref mcp`, pure stdlib) so an
agent can run the whole loop — `search_corpus`, `cite_claim`, `create/run_experiment`,
`log_decision`, `weave`, read-only `query` — through the same code paths and the
same §0 constraints as the CLI. See [`AGENTS.md`](AGENTS.md) for the operating
protocol.

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
uv sync --extra pdf --extra anchor                            # light, recommended
uv sync --extra parse-sota --extra embed-local --extra verify-local   # full SOTA (needs torch)
```

## Layout

```
reref/          the engine (indexing, retrieval, anchoring, verification)
tests/          dependency-free unit + integration tests
library/        SHARED corpus of reference papers (index once)
.reref/         shared index + lockfile (derived)
projects/       one folder per paper: ideation.md, src/, text/, citations.json
pyproject.toml  project + extras (uv-managed)
uv.lock         pinned dependency lockfile (commit this)
```
