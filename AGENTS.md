# AGENTS.md — operating protocol for this research environment

This repo is an auto-research environment: a shared paper corpus + the `reref`
engine + a central research database (`.research/env.db`). You (an agent)
operate it through the `reref` **CLI** or the **`reref` MCP tools** — both go
through the same code paths, so the rules below hold either way.
`docs/BLUEPRINT.md` has the full design; this file is what you follow.

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
   manuscript numbers and bibliography are woven from the store (`reref
   weave`). If you want a status to change, produce the evidence.
6. **The graph is a view of the ledger.** Every canvas gesture maps to a
   domain write or is refused with the store's reason (e.g. an experiment
   backs a claim only via a completed run). Node positions are presentation
   state, nothing more.
7. **Metric names are standardized via the registry** (`reref metric define`):
   label, unit, direction, format — rendered identically in CLI, web, and
   weave. Registration is optional and never blocks a run.
8. **The cockpit's admin surface edits allowlisted instruction files and
   settings — never code.** Agent behavior is controlled through AGENTS.md;
   tool prompts stay in code and defer to it.
9. **stdlib-first.** The core runs dependency-free; heavy SOTA backends are
   optional extras.

## The operating loop

1. **Restore context first**: `reref exp list <project>` + `reref log list
   <project>` (or the `status` tool) before any work.
2. **Source every claim**: prior work → `cite_claim`; results → a recorded
   run. No exceptions.
3. **Log before you pivot**: direction changes are `decision` entries written
   *before* the work. Open items are `question` entries (answer them later
   with `--answers <id>`); external input is `feedback` with a `--source`.
4. **One experiment, one question**: new hypothesis → new experiment,
   `--parent` chains the DAG. Branch; don't mutate finished experiments.
5. **Results are generated, never typed**: entrypoints read
   `REREF_RUN_DIR`/`REREF_PARAMS`, write `metrics.json`; numbers flow
   run → metric → paper via `reref weave`.
   **Cluster runs** (compute/data stay remote): register remote data with
   `dataset add --remote ssh://… --sha256 <hashed-on-cluster>`; after the run,
   `reref exp ingest <project> <slug> --dir <copied-dir>` — or, when nothing
   comes home, `--metrics '{…}' --remote ssh://…` (MCP: `ingest_run`).
   Provenance grades `remote`, or `remote-verified` if the cluster wrapper
   wrote `provenance.json` (git_sha, params, seed, env_hash) into the run dir.
   §0 unchanged: a result still only enters via a recorded run.
   Per-step curves (TensorBoard events etc.) are TELESCOPE artifacts — never
   citable; only `metric` rows feed the paper.
6. **Snapshot for git**: `reref export` after meaningful changes.

## Finding things

CLI and MCP tools are 1:1 — discover them with `uv run reref --help` (or the
MCP tool list; server `reref` in `.mcp.json`). `query` is read-only SQL over
the whole store.

**Web cockpit:** `https://research.com/` (local: /etc/hosts + a mkcert-trusted
cert; http redirects) — starts ON DEMAND (launchd socket activation) on the
first request and exits after 30 min idle, so never start it manually when the
agent is set up. Manual fallback: `uv run reref web` (→ 127.0.0.1:8765).
One-time setup: `uv run reref web install [--domain … --https]` + the printed
/etc/hosts and `mkcert -install` steps. It is a plain local process, not
Docker — it must read/write this repo's working tree.

## Where state lives

- `library/` — shared reference corpus, indexed into `.reref/` (derived).
- `.research/env.db` — the ground truth (gitignored); `.research/export/`
  JSONL is the committed snapshot.
- `projects/<slug>/` — one paper: `src/`, `text/`, `runs/` — its own git repo.
