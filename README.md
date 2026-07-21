<h1 align="center">renv</h1>

<p align="center"><b>The local-first research environment where every claim shows its work.</b></p>

<p align="center">
  <a href="https://github.com/julianwinking/renv/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/julianwinking/renv/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg" /></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg" />
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
so they are self-verifying. A `renv publish` step that puts the verifiable
graph behind a finished paper on renv.ai is planned but not live yet.

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
- **Lean core.** One small pure-Python dependency (PDF parsing) and nothing
  else; it installs in seconds. Heavy SOTA backends are optional extras
  behind lazy imports.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (Python 3.10+); the cockpit build
needs [Node](https://nodejs.org/).

```bash
git clone https://github.com/julianwinking/renv && cd renv
uv sync

# 1. the cockpit — the all-in-one research UI
uv run renv web install     # one command: builds the UI + https://renv.local
                            # (macOS on-demand site; asks once for sudo + keychain)
# …or with zero system changes:
(cd cockpit && npm install && npm run build)
uv run renv web             # http://127.0.0.1:8765

# 2. put .txt/.md/.pdf papers in library/  (two demo papers are included)
uv run renv index                           # index the shared corpus

# 3. cite the corpus from a project — or just read on in the cockpit's Papers tab
uv run renv cite "Citation precision uses NLI to flag unsupported passages." projects/span-citation --write
uv run renv status projects/span-citation   # corpus + project state
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

The **React cockpit** ([`cockpit/`](cockpit/)) is the all-in-one UI for
driving a project: the paper library with a PDF reader (span-anchored
citations and reference intelligence highlighted in place), the
claim/evidence graph, experiment branches with runs and metrics, findings
review, the decision log, and the full interactive canvas. Setup is in the
Quickstart above; `renv web uninstall` reverses the renv.local install, and
system changes only ever happen through that explicit command, never on
package install. Development mode and details: [`cockpit/README.md`](cockpit/README.md).

## Drive it from an agent (MCP)

`.mcp.json` registers a local stdio MCP server (`renv mcp`, pure stdlib) so
an agent can run the whole loop: `search_corpus`, `cite_claim`,
`create/run_experiment`, `log_decision`, `weave`, and read-only `query`,
through the same code paths and constraints as the CLI.
[`AGENTS.md`](AGENTS.md) is the operating protocol.

## Publishing (planned)

`renv publish` — pushing a paper's verifiable subgraph (claims, evidence,
runs, span citations) to renv.ai as an interactive companion — is a planned
future feature. It is not currently served on https://renv.ai; the engine is
fully usable without it.

## Optional SOTA backends

The defaults (TF-IDF retrieval, lexical verification, pdfminer parsing) are
fast and dependency-light. Drop-in SOTA upgrades — local embeddings, NLI-based
citation verification, layout-aware parsing — live behind extras
(`uv sync --extra verify-local` etc.); the full matrix is in
[CONTRIBUTING.md](CONTRIBUTING.md).

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



## License

[MIT](LICENSE) © Julian Winking
