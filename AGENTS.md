# AGENTS.md — operating protocol for this research environment

This repo is an auto-research environment: a shared paper corpus + the `reref`
engine + a central research database (`.research/env.db`) that records every
experiment, decision, and citation. You (an agent, e.g. Claude Code) operate it
either through the `reref` **CLI** or the **`reref` MCP tools** — both go through
the same code paths, so the rules below hold no matter which you use.

Read `docs/BLUEPRINT.md` for the full design. This file is the protocol you follow.

## The one invariant (§0): every fact has one source of truth

| Fact | Lives in | You must |
|---|---|---|
| "the literature says X" | a `citation` (span-anchored) | `cite_claim` it — never paraphrase a source from memory |
| "I measured Y" | a `metric` from a `run` | produce it via `run_experiment` — never type a number |
| "I decided Z because…" | a typed `log_entry` | `log_decision` it *before* acting on it |

A `result` log entry **without** a linked run is rejected at the write boundary.
Run `reref log check` (or the `check_invariants` tool) to audit the whole DB.

## The operating loop

1. **Restore context first.** Before working in a project, read its state:
   `reref exp list <project>` and `reref log list <project>` (or the `status`
   tool). Never start work blind to what was already tried.
2. **Source every claim.** A statement about prior work → `cite_claim`. A
   statement about a result → it must come from a recorded run. No exceptions.
3. **Log before you pivot.** Any change of direction is a `decision` entry with a
   rationale (`body_md`), written *before* the work — not reconstructed after.
4. **One experiment, one question.** New hypothesis → `create_experiment` (set
   `parent` to chain it onto the DAG). Don't mutate a finished experiment; branch.
5. **Results are generated, never typed.** Numbers flow `run → metric → paper`.
   The runner contract: your entrypoint reads `REREF_RUN_DIR` + `REREF_PARAMS`
   (JSON) from the environment and writes `metrics.json` (a flat `{name: value}`)
   plus any artifact files into `REREF_RUN_DIR`.
6. **Snapshot for git.** After meaningful changes, `reref export` writes the
   deterministic JSONL snapshot that is the committed record of state.

## Tool reference

CLI (`uv run reref …`) and MCP tools are 1:1:

| Do | CLI | MCP tool |
|---|---|---|
| init / migrate DB | `db init` | — |
| new project | `project new <slug>` | `create_project` |
| corpus state / project state | `status [project]` | `status` |
| retrieve spans (RAG) | `resolve "<q>"` | `search_corpus` |
| cite + verify a claim | `cite "<claim>" <project>` | `cite_claim` |
| new experiment | `exp new <project> <slug> [--parent]` | `create_experiment` |
| the DAG + metrics | `exp list <project>` | `list_experiments` |
| experiment + its runs | `exp show <project> <slug>` | `get_experiment` |
| run (reproducible) | `exp run <project> <slug> --entrypoint …` | `run_experiment` |
| log a decision/result | `log add <project> <type> "<body>"` | `log_decision` |
| read the log | `log list <project>` | `list_log` |
| audit §0 | `log check` | `check_invariants` |
| meeting note | `note add <project> "<body>"` | `add_note` |
| register eval data | `dataset add <slug> [--path]` | `register_dataset` |
| read-only SQL | — | `query` |
| export for git | `export` | — |

The MCP server is registered in `.mcp.json` (`reref` server). `query` is
read-only; all write tools enforce the §0 constraints above.

## Where knowledge lives: files are instructions, the store is state

- **Markdown files are low-churn instructions for agents**: this protocol, the
  writing guides in `templates/writing/` (paper structure, thesis structure,
  reusable phrasing — read them *before drafting manuscript text*), and the
  project templates. They change rarely and load straight into context.
- **All research state lives in the store and its graph** — ideation, theses,
  contributions, open questions, hypotheses, decisions, results, feedback —
  as claims / log entries / notes. There is no `ideation.md`: state the thesis
  as a claim, risks as `question` entries, the evaluation design as a
  `decision` entry *before* building.
- **Layering, not copies.** Each project's `AGENTS.md` holds ONLY
  project-specific overrides and defers to this file. Never duplicate protocol
  text into a project — that is how drift starts.

## Where state lives

- `library/` — shared reference corpus (papers). Indexed once into `.reref/`.
- `.research/env.db` — the single ground truth (ignored by git; the JSONL export
  under `.research/export/` is the committed artifact).
- `projects/<name>/` — one paper: `src/` (experiment code), `text/` (manuscript),
  `runs/<id>/` (run artifacts). Each project is its own git repo.
