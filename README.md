<h1 align="center">renv</h1>

<p align="center"><b>The local-first research environment where every claim shows its work.</b></p>

<p align="center">
  <a href="https://github.com/julianwinking/renv/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/julianwinking/renv/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg" /></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg" />
  <a href="https://renv.ai"><img alt="renv.ai" src="https://img.shields.io/badge/publish-renv.ai-10b981.svg" /></a>
</p>

---

renv is a research environment that runs on your machine. One SQLite
database is the single ground truth for everything a project knows: papers,
span-anchored citations, experiments, runs, metrics, claims, and the decision
log. Your AI drives it through MCP, you drive it through a CLI and a local web
cockpit, and all three go through the same domain functions.

The result is research state you can audit. Measured numbers can only enter
the record through recorded runs. Claim status is derived from linked
evidence, never asserted. Citations anchor to the exact quoted source span,
so they are self-verifying. When a paper is ready, `renv publish` puts the
verifiable graph behind it on [renv.ai](https://renv.ai) as an interactive
companion.

## Why renv

- **One store, thin clients.** CLI, MCP server, and web cockpit are shells
  over the same SQLite ground truth. There is no second copy of anything.
- **Span-anchored citations.** The citation anchor is the quoted text itself
  (W3C TextQuoteSelector plus TextPosition), verified against your claim and
  emitted as a LaTeX `\spancite`. Anchors survive re-indexing and new document
  versions because they never reference chunk or vector ids.
- **Experiments form a DAG.** One experiment, one question. Branch instead of
  mutating; every run pins git sha, env hash, dataset, and seed.
- **Provenance, enforced.** A `result` log entry is rejected unless it links a
  completed run, and `renv log check` re-audits the whole store. This
  guarantees provenance, not validity: a buggy run can still produce a wrong
  number.
- **Claims traced to evidence.** Supported or refuted is computed from linked
  runs and citations. Reviews flag any thesis claim that is still open.
- **Numbers are woven, never typed.** `renv weave` regenerates the results
  table and bibliography straight from the store, so the manuscript cannot
  drift from the data.
- **Agent-native.** The repo ships a stdio MCP server and an operating
  protocol ([`AGENTS.md`](AGENTS.md)). An agent runs the whole loop through
  the same code paths and constraints as the CLI.
- **stdlib-first.** The core has zero runtime dependencies and installs in
  seconds. Heavy SOTA backends are optional extras behind lazy imports.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). The default stack is stdlib-only,
so one sync gives you a working environment with nothing to compile.

```bash
git clone https://github.com/julianwinking/renv && cd renv
uv sync

# 1. put .txt/.md/.pdf papers in library/  (two demo papers are included)
uv run renv index                           # index the shared corpus
uv run renv status projects/span-citation   # corpus + project state

# 2. cite the corpus from a project
uv run renv cite "Citation precision uses NLI to flag unsupported passages." projects/span-citation --all
uv run renv cite "..." projects/span-citation --write   # -> citations.json

uv run renv resolve "smaller passages are easier to verify"
uv run renv preamble                        # LaTeX \spancite macro
uv run pytest                                # run the test suite
```

Prefer to let your agent do the setup? Paste this into Claude Code or Codex:

```
Set up renv from https://github.com/julianwinking/renv: clone it, run 'uv sync',
index the demo library with 'uv run renv index', then show me my first
span-anchored citation with 'uv run renv cite'.
```

## How it works

One shared corpus, many papers. The engine (`renv/`) and the corpus
(`library/` plus the derived `.renv/` index) live at the repo root. Each
paper you write is a project under `projects/` that retrieves against that
one corpus.

```
library/*.pdf ── parse ──> text + char offsets
              ── chunk ──> sentence-level passages with offsets
              ── embed ──> vectors ──> shared index + lockfile (.renv/)

claim ── retrieve ──> candidate passages
      ── anchor   ──> W3C TextQuote + TextPosition selectors
      ── verify   ──> does the span support the claim? (full / partial / none)
      ── cite     ──> \spancite{src}{start}{end}{quote} + citations.json
```

`.renv/renv.lock.json` pins parser, chunker, and embedder versions plus a
sha256 per source file, so a collaborator reproduces an identical index from
the same corpus.

## The research store

Beyond citations, renv tracks what you did, in what order, and why in one
central SQLite database (`.research/env.db`).

```bash
uv run renv db init                          # create/migrate the env DB
uv run renv project new span-citation        # DB row + workspace dirs

# experiments form a DAG (one experiment, one question)
uv run renv exp new span-citation 001-tfidf --title "TF-IDF baseline"
uv run renv exp new span-citation 002-dense --parent 001-tfidf

# runs are reproducible: the entrypoint reads RENV_RUN_DIR + RENV_PARAMS and
# writes metrics.json; git sha, env hash, dataset, config hash, and seed are pinned
uv run renv exp run span-citation 001-tfidf --entrypoint run.py --param k=8

# the decision log: numbers may only enter via a recorded run
uv run renv log add span-citation result "recall hit 0.8" --evidence run:1
uv run renv log check                        # audit the provenance invariant

# claims are first-class and traced to evidence
uv run renv claim add span-citation "Span anchoring beats paper-level citation" --kind thesis
uv run renv claim link 1 --cite 3 --stance supports
uv run renv claim list span-citation         # status is DERIVED from evidence

uv run renv weave span-citation              # regenerate results table + bibliography
uv run renv export                           # deterministic JSONL snapshot for git
```

Long experiments run in the background so they never block an agent, and the
runner withholds secret-named environment variables by default. Cluster runs
are supported through registered ssh remotes with graded provenance; see
[`AGENTS.md`](AGENTS.md).

## The web cockpit

```bash
uv run renv web                 # http://127.0.0.1:8765
```

One frontend, the **React cockpit** ([`cockpit/`](cockpit/)): experiment
branches, claims, findings, citations, and papers as connected, expandable
nodes on an interactive canvas, plus a tabbed PDF viewer that highlights each
cited span in place. Until it is built, the server answers with a
build-instructions page (the JSON API works either way).

```bash
cd cockpit && npm install && npm run build   # build once; renv web serves it
```

On macOS, `./install.sh` sets up an on-demand local site with TLS
(launchd socket activation, mkcert) so the cockpit starts on first request and
exits when idle. See the script for details.

## Drive it from an agent (MCP)

`.mcp.json` registers a local stdio MCP server (`renv mcp`, pure stdlib) so
an agent can run the whole loop: `search_corpus`, `cite_claim`,
`create/run_experiment`, `log_decision`, `weave`, and read-only `query`,
through the same code paths and constraints as the CLI.
[`AGENTS.md`](AGENTS.md) is the operating protocol.

## Publish to renv.ai

When a paper is ready, publish the clean, publishable subgraph (thesis and
contribution claims, their evidence, the experiments and runs behind that
evidence, cited papers with span citations) to [renv.ai](https://renv.ai):

```bash
renv publish span-citation
# → live at renv.ai/<you>/span-citation
```

Readers get the scaffolding a PDF hides: how well-backed each claim is, which
run produced which number, and the exact source span behind every citation.
The engine stays fully usable without the platform.

## Optional SOTA backends

Defaults are lightweight; verified SOTA picks are drop-in adapters behind
optional extras. All options are commercially permissive.

| Layer | Default | Upgrade |
|---|---|---|
| PDF parse | `pdfminer.six` | **Docling** (`page_no` + `bbox` + `charspan`) |
| Embeddings | builtin TF-IDF | **Qwen3-Embedding-0.6B** / **BGE-M3** |
| Span citation | retrieve + anchor | **LongCite-llama3.1-8b** |
| Verify support | lexical overlap | **FactCG-DeBERTa-v3** |
| Re-anchor | stdlib `difflib` | **RapidFuzz** |

```bash
uv sync --extra pdf --extra anchor                                    # light
uv sync --extra parse-sota --extra embed-local --extra verify-local   # full (needs torch)
```

## Repository layout

```
renv/          the engine: indexing, retrieval, anchoring, verification,
                store, experiments, claims, weave, CLI, MCP server, web API
cockpit/        the React cockpit UI (build once; served by `renv web`)
tests/          dependency-free unit + integration tests
library/        shared corpus of reference papers (index once)
.renv/         derived index + lockfile
projects/       one folder per paper (each its own git repo)
AGENTS.md       the operating protocol for agents (and humans)
```

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md)
for the workflow and the design invariants PRs are reviewed against. CI runs
the test suite on the oldest and newest supported Python plus a cockpit build.
Security issues: please report privately via
[GitHub security advisories](https://github.com/julianwinking/renv/security/advisories/new).

## Citation

If renv is useful in your research, please cite it:

```bibtex
@software{winking2026renv,
  author = {Winking, Julian},
  title  = {renv: a local-first research environment with span-anchored, verified citations},
  year   = {2026},
  url    = {https://github.com/julianwinking/renv}
}
```

Projects published on renv.ai additionally get a per-project citation with a
stable URL.

## License

[MIT](LICENSE) © Julian Winking
