# AGENTS.md — operating protocol for this research environment

This repo is an auto-research environment: a shared paper corpus + the `renv`
engine + a central research database (`.research/env.db`). You (an agent)
operate it through the `renv` **CLI** or the **`renv` MCP tools** — both go
through the same code paths, so the rules below hold either way.
This file is what you follow.

## Architecture decisions (do not re-litigate these in a session)

1. **One store, thin clients.** The SQLite DB is the single ground truth;
   CLI, MCP, and web cockpit are thin shells over the same domain functions.
   Never write to the DB with raw SQL; never re-implement a domain rule in a
   client.
2. **§0 — one home per fact-type.** Literature facts are span-anchored
   `citation`s, measured numbers are `metric` rows from a `run`, reasoning is
   typed `log_entry`s. This is *provenance* enforcement (write boundary +
   `log check` audit), not a proof of validity.
3. **Files are instructions, the store is state.** Markdown = low-churn agent
   instructions only: this protocol, `templates/writing/` (paper structure,
   thesis structure, reusable phrasing — read before drafting manuscript
   text), and the project templates. ALL research state — ideation, theses,
   contributions, questions, hypotheses, decisions, feedback — lives in the
   store/graph as claims, log entries, and notes. There is no `ideation.md`
   and no planning markdown, ever: it would be a second, drifting copy of
   graph state.
4. **Layering, not copies (anti-drift).** A project's `AGENTS.md` contains
   ONLY project-specific overrides and defers to this file. No symlinks
   (projects are standalone git repos and clones would dangle); no duplicated
   protocol text.
5. **Status is derived, never hand-set.** Claim status comes from linked
   evidence (runs/citations), question status from an answering entry,
   manuscript numbers and bibliography are woven from the store (`renv
   weave`). If you want a status to change, produce the evidence.
6. **The graph is a view of the ledger.** Every canvas gesture maps to a
   domain write or is refused with the store's reason (e.g. an experiment
   backs a claim only via a completed run). Node positions are presentation
   state, nothing more.
7. **Metric names are standardized via the registry** (`renv metric define`):
   label, unit, direction, format — rendered identically in CLI, web, and
   weave. Registration is optional and never blocks a run.
8. **The cockpit's admin surface edits allowlisted instruction files and
   settings — never code.** Agent behavior is controlled through AGENTS.md;
   tool prompts stay in code and defer to it.
9. **Lean core.** The core carries one small pure-Python dependency
   (pdfminer.six); heavy SOTA backends are optional extras.
10. **Clients split on touch, never big-bang.** cli.py / web.py / mcp_server.py
    are long-but-flat shells; wholesale splitting moves thousands of lines for
    zero invariant gain (the domain boundary is already test-enforced). A new
    command or route surface starts as its own module; existing ones migrate
    only when a change touches them anyway. web.py's if-chain becomes a
    dispatch table at its next substantive change.
11. **No typing retrofit.** The dict-row domain style caps a type checker's
    value (measured: 38 mypy errors, all Optional/dict-shape noise, zero of
    this codebase's real bugs). Correctness lives in executable invariants,
    the test suite, and ruff. Annotate new pure-logic modules as written;
    revisit only if outside contributors arrive or a bug appears that typing
    would demonstrably have caught.

## The operating loop

1. **Restore context first**: `renv exp list <project>` + `renv log list
   <project>` (or the `status` tool) before any work.
2. **Source every claim**: prior work → `cite_claim`; results → a recorded
   run. No exceptions.
3. **Log before you pivot**: direction changes are `decision` entries written
   *before* the work. Open items are `question` entries (answer them later
   with `--answers <id>`); external input is `feedback` with a `--source`.
4. **One experiment, one question**: new hypothesis → new experiment,
   `--parent` chains the DAG. Branch; don't mutate finished experiments.
5. **Results are generated, never typed**: entrypoints read
   `RENV_RUN_DIR`/`RENV_PARAMS`, write `metrics.json`; numbers flow
   run → metric → paper via `renv weave`.
   **Cluster runs** (compute/data stay remote): clusters are registered
   remotes (`renv remote list` / MCP `list_remotes`) referencing ssh aliases
   — `ssh <name>` is how you reach them; locators like `snaga:runs/exp42`
   expand against the remote's data root. Register remote data with
   `dataset add --remote ssh://… --sha256 <hashed-on-cluster>`; after the run,
   `renv exp ingest <project> <slug> --dir <copied-dir>` — or, when nothing
   comes home, `--metrics '{…}' --remote ssh://…` (MCP: `ingest_run`).
   Provenance grades `remote`, or `remote-verified` if the cluster wrapper
   wrote `provenance.json` (git_sha, params, seed, env_hash) into the run dir.
   §0 unchanged: a result still only enters via a recorded run.
   Per-step curves (TensorBoard events etc.) are TELESCOPE artifacts — never
   citable; only `metric` rows feed the paper.
6. **Snapshot for git**: `renv export` after meaningful changes.

## The claim/citation loop (the core write path — follow exactly)

```
renv add refs.bib                       # cold-start: .bib import (arXiv/DOI entries
                                         #   resolve, keyed by bib key; rest reported)
renv add <pdf|arxiv|doi> [--key K]      # one paper; a landed file is ALWAYS named
                                         #   <key>.<ext> (identity invariant); --key on
                                         #   an existing key ATTACHES text to that paper
renv index                              # after anything lands in library/

renv claim add <proj> "<text>" --kind thesis|contribution|assertion|hypothesis
renv cite "<claim text>" <proj> --source <paper_key> --write
                                         # pin --source when you know the paper; prints
                                         #   `citation row: #N` — N is what you link.
                                         #   support='none' is refused without --force.
renv claim link <id> --cite N --stance supports|refutes|inconclusive \
                [--grade anecdotal|suggestive|confirmatory]
renv claim relate <id> <related> --kind depends_on|contradicts
```

Rules of thumb the loop depends on:
- Word `cite` claims close to the source's phrasing — the default lexical
  verifier scores token overlap, not entailment; a correct paraphrase can score
  'none'. Semantic verification: `--verifier factcg` (verify-local extra).
- Inspect/repair citations with `renv citation list <proj>` and
  `renv citation rm <id> [--force]` (tombstones, never deletes — history stays).
- One `cite` call anchors ONE span; a claim needing k sources takes k
  cite+link rounds, each with its own `--source`.
- Papers ingested by DOI have metadata but NO text — span citations cannot
  anchor to them until a PDF is attached (`renv add <pdf> --key <key>`).
- `project` arguments accept a slug or a `projects/<slug>` path everywhere in
  the loop above; both resolve to the slug.
- Never open the SQLite file to look around — `renv query "SELECT …"` is the
  read-only escape hatch (CLI and MCP `query` are the same).
- If an old corpus has a library file whose stem ≠ its paper key (citations
  print `no paper row`), repair with `renv papers --rekey <stem> <key>` + reindex.
- A paper's own bibliography: `renv references build|list <key>` parses its
  References section and traffic-lights each entry against the corpus
  (library / unknown / not_relevant); `references add <id>` ingests a cited
  paper (→ the reading inbox), `references mark <id> --comment "why"` dismisses
  it. `renv inbox` lists papers no human has read yet; agents NEVER mark
  papers read (`inbox --read` is the human's move).

## Finding things

CLI and MCP tools are 1:1 — discover them with `uv run renv --help` (or the
MCP tool list; server `renv` in `.mcp.json`). `query` is read-only SQL over
the whole store.

**Web cockpit:** `https://research.com/` (local: /etc/hosts + a mkcert-trusted
cert; http redirects) — starts ON DEMAND (launchd socket activation) on the
first request and exits after 30 min idle, so never start it manually when the
agent is set up. Manual fallback: `uv run renv web` (→ 127.0.0.1:8765).
One-time setup: `uv run renv web install [--domain … --https]` + the printed
/etc/hosts and `mkcert -install` steps. It is a plain local process, not
Docker — it must read/write this repo's working tree.

## Where state lives

- `library/` — shared reference corpus, indexed into `.renv/` (derived).
- `.research/env.db` — the ground truth (gitignored); `.research/export/`
  JSONL is the committed snapshot.
- `projects/<slug>/` — one paper: `src/`, `text/`, `runs/` — its own git repo.
