# research-env — System Blueprint

The full design for an individual auto-research environment. Eight MECE pillars,
one cross-cutting invariant, a phased build plan. Pillar 3 (Cite) is the only one
substantially built today; this document specifies the other seven and how they
compose.

---

## 0. The organizing principle: single source of truth per fact-type

Every sentence in a finished paper is one of four kinds of fact. Each kind has
exactly **one** authoritative home in this system. Nothing is hand-retyped from
one home into another — the manuscript is *assembled* from these sources, never
restated. This is the anti-hallucination spine.

| Fact-type | Authoritative home (a table in the one store) | Pillar |
|---|---|---|
| "The literature says X" | a **`citation`** row anchored to a source span | 2 / 3 |
| "I measured Y" | a **`metric`** row from a `run` (config-pinned) | 5 |
| "I decided Z because…" | a **`log_entry`** row (prose in `body_md`) | 5 |
| "The argument is…" | the **manuscript**, a generated document referencing the above | 6 |

**Invariant:** no number or claim enters a `log_entry` or the paper unless it
traces to a `citation` or a `run`. This is enforced **at the service-layer write
boundary** — `log.add_entry` rejects a `result` whose run evidence is missing, of
another project, or not a *done* run — and **audited** across the whole DB by
`reref log check` (catching any out-of-band write). It is *not* a SQLite CHECK/
trigger (those can't express cross-row existence here); the guarantee is
write-boundary enforcement + audit, which is what `check_invariants` backstops.

**What this does and does NOT give you (read this).** The invariant guarantees
*provenance*: a number in the paper traces to a recorded run. It does **not**
guarantee the run was correct, the config right, or the metric faithfully labeled —
a buggy entrypoint that writes `recall=0.99` still passes. This is provenance
enforcement plus automated checks, not a proof of validity. See **Honest status**
below for the full list of what is real vs. aspirational.

```
                       ┌─────────────── Pillar 7: Orchestrate (AGENTS.md protocol) ───────────────┐
                       │  enforces: read context → log reasoning → cite or run → assemble          │
   world ── Ingest ──▶ Knowledge base ──▶ Cite ──┐                                                  │
    (1)        (1)          (2)            (3)    │                                                  │
                                                  ├─▶ Manuscript (6) ◀── Experiment results (5) ◀── Ideate (4)
                                                  │                                                  │
                       └──────────────────────────┴──────────────────────────────────────────────┘
```

---

## Honest status (after three adversarial reviews, 2026-06-30)

Three independent reviewers (code-correctness, design/MECE, research-methodology)
audited the build. Their convergent verdict: the **provenance/bookkeeping spine is
real and sound; several headline *guarantees* were overstated** and some advertised
capabilities aren't built yet. This section is the honest ledger.

**Real & working** (built, tested): the SQLite store + migrations + deterministic
export; the experiment DAG; the reproducible runner (now timeout-guarded, failure-
recording, provenance-graded); the decision log with write-boundary §0 enforcement;
span-anchored verified citations; `weave` (numbers generated from metrics); the
review rubric + automated checks; **finding adjudication with dedup-by-memory**;
the code↔store `@reref` tag convention; the MCP server (28 tools); the project
template + `reref new`.

**Corrected overclaims** (docs now match code): "anti-hallucination by construction"
→ *provenance enforcement + checks* (a run can still be wrong); "DB constraint" →
*write-boundary + audit*; "full reproduction tuple" → *provenance tuple, graded
complete/degraded* (does NOT capture hardware/GPU/library nondeterminism).

**Now built (Round 2):**
- **Claim/evidence graph is LIVE** (`reref/claim.py`): claims (thesis/contribution/
  assertion) attach to citations and runs (supports/refutes); status is *derived*
  from evidence; review flags any open thesis/contribution claim. The backbone the
  reviewers found dead is now wired and used. CLI `reref claim …`; 4 MCP tools.
- **Web cockpit** — two frontends over one JSON API (`reref web`, stdlib
  http.server, 127.0.0.1): (a) a **buildless page** (`reref/web/index.html`) —
  dashboard, papers + usage map, branch explorer, findings accept/reject, claim
  graph, timeline; (b) a **React Flow graph app** (`cockpit/`, Vite + `@xyflow/react`
  + dagre) — experiment branches / claims / findings / citations / papers as
  connected, expandable interactive nodes with inline adjudication and claim→evidence
  edges. `reref web` serves `cockpit/dist` when built, else the buildless page.
  Backend exposes `/api/graph/<slug>` (neutral nodes+edges) + CORS. Writes go
  through the same domain functions as CLI/MCP.

**Now built (Round 3 — roadmap cleared):**
- **Single citation home:** the `citation` table is the source of truth;
  `citations.json` is a *derived* view (`regenerate_sidecar`), written by CLI + MCP +
  `weave`. Review/weave read the table. §0 wrinkle resolved.
- **KB search:** `reref search` / MCP `search` — FTS5 over papers/cards/notes/log/
  claims (LIKE fallback). **Literature discovery:** `reref discover` / MCP
  `discover_papers` (arXiv keyword search → ingest). **Async runs:** `start_run` +
  `run_status` run in a background thread so a long job never blocks the MCP server.
  **Export is round-trippable** (`reref import`) and **project-scoped**
  (`reref export --project`). **Secrets:** the runner withholds secret-named env vars
  by default (`--env-allow` to opt one in). **Code↔store graph edges:** `@reref` tags
  render as code nodes wired to their finding/experiment/paper/claim.

**Remaining (small, deliberately deferred):**
- **Statistical rigor** (multi-seed/variance/CI/significance) — by design a
  per-project concern, not built into the core.
- Minor polish from the reviews: hand-edited generated `.tex` isn't checksum-guarded;
  bib-key reconciliation assumes filename-stem == paper key; sidecar had no dedup
  (now moot since it's regenerated from the table).

---

## Core architecture: one store, three clients

The structured state of the whole environment is **relational data**, so it lives
in **one embedded SQLite database** (`.research/env.db`), accessed only via the
stdlib `sqlite3` module — no new dependency, no server daemon. SQLite is chosen
because the data is relational (configs linked to runs, citations linked to
papers), it is a single durable portable file, and FTS5 gives full-text/RAG search
for free. **It is the single ground truth**; the web cockpit, the MCP server, and
the `reref` CLI are three *clients* over it, so nothing can drift.

```
        ┌──────────── reref engine (parse / anchor / verify / retrieve) ───────────┐
        │                                                                            │
        │     ┌──────────────────────────────────────────────────────────────┐     │
 truth ─┼────▶│   SQLite  .research/env.db    +    deterministic git text export │◀──┤
        │     └──────────────────────────────────────────────────────────────┘     │
        │              ▲                      ▲                      ▲                │
        └──────────────┼──────────────────────┼──────────────────────┼───────────────┘
              web cockpit (human)        MCP server (agent)      reref CLI (scripts)
```

**Markdown's role.** Prose — decision rationale, meeting notes, section drafts —
lives in `TEXT`/`body_md` columns *inside* the DB, and is *rendered* to Markdown/
HTML for reading. Markdown is a view, not the store. The manuscript (LaTeX) stays a
document on disk, but its numbers and citations are generated from DB queries.

**Schema (core tables, FKs shown with →; integer surrogate PKs + human slugs):**
```
project(id, slug, title, status, created)
paper(id, key, title, authors, year, doi, arxiv, sha256, tags, added)
card(id, paper_id→paper, field, text, anchor, extracted_by, model, generated)  -- structured extraction (Pillar 2)
dataset(id, slug, version, sha256, description, created)         -- eval data, versioned + hashed   [crit #2]
experiment(id, project_id→project, parent_id→experiment, slug, title, hypothesis, status, created, completed)  -- parent = DAG edge
config(id, hash, params_json)                        -- one config, many runs; hash dedups   ← reproducibility
run(id, experiment_id→experiment, config_id→config, dataset_id→dataset,
    git_sha, env_hash, corpus_lock_hash, seed, status, started, finished)       -- full reproduction tuple   [crit #3]
metric(id, run_id→run, name, value, split)           -- SOLE home of every number
artifact(id, run_id→run, path, sha256, kind)         -- large outputs (figures/checkpoints) stay on disk
citation(id, project_id→project, paper_id→paper, claim_text, src_start, src_end, quote, prefix, suffix,
         support, support_score, manuscript_loc)     -- src_*: span into source; manuscript_loc: where in YOUR draft
claim(id, project_id→project, text, kind, manuscript_loc, status)   -- thesis|contribution|assertion   [crit #1]
claim_evidence(id, claim_id→claim, citation_id→citation NULL, run_id→run NULL, stance)  -- supports|refutes
log_entry(id, project_id→project, experiment_id→experiment NULL, type, ts, body_md)  -- prose
log_evidence(id, log_entry_id→log_entry, run_id→run NULL, citation_id→citation NULL)  -- enforces §0 invariant
note(id, project_id→project, ts, title, body_md)     -- meeting notes
```

The **claim/evidence graph** (`claim` + `claim_evidence`) is the research backbone:
every assertion in the manuscript resolves to a citation or a run, so Pillar 8 can
check "does each claim trace to evidence?" mechanically and Pillar 6 assembles an
honest paper. It cuts across Pillars 4/5/6/8 but is *data*, not a pillar.

### Engineering invariants (so the store stays clean under three writers)

- **One service layer.** `reref/db.py` (connection + schema + migrations + export)
  plus domain modules (`experiment.py`, `log.py`, `dataset.py`, …) are the *only*
  path to the DB. CLI, MCP, and web are thin shells over these functions — no
  client re-implements logic, so the §0 constraints hold everywhere.   [crit #4]
- **Connection discipline.** `PRAGMA foreign_keys=ON`, `journal_mode=WAL`,
  `busy_timeout` — safe concurrent reads + serialized writes across clients. The
  `query` tool opens a **read-only** (`mode=ro`) connection; no client runs
  arbitrary write SQL.   [crit #5]
- **Migrations.** Schema versioned via `PRAGMA user_version` + an ordered migration
  list; `connect()` migrates forward idempotently. Never an ad-hoc `ALTER`.
- **The §0 invariant is enforced at the write boundary.** `log.add_entry` rejects a
  `result` entry with no `run` evidence; `reref status`/`check` audits the whole DB
  for violations (catching any raw-SQL backdoor writes).

**Reproducibility & git.** The binary `.db` doesn't diff well, so an explicit
`reref export` writes a **deterministic text snapshot** (one JSONL file per table,
rows ordered by id, sorted keys) that *is* committed — diffs, durability, and
code-review of state, without losing SQL/joins. Export is a command (+ optional
git pre-commit hook), **not** a per-write side effect.
Large blobs never enter SQLite: `artifact` rows point at on-disk files by
`path + sha256`. The DB lives centrally — **one `.research/env.db` covering the
corpus + all projects** (like the shared `library/` + `.reref/`), so cross-project
queries work; each project's git repo carries its own slice of the export.

### The web cockpit (human client) — minimal, clean, read+write

The cockpit is the *human* interface to the one store; an agent does the same
things through the MCP server. Both mutate via the **same engine code paths**, so
every DB constraint holds regardless of who acts, and the two see identical live
state. Views:

1. **Dashboard** — minimal at-a-glance: active project, latest runs + their key
   metrics, recent decisions, open review findings, corpus size.
2. **Papers** — the library: searchable (FTS5) list with metadata + tags; open one
   → its structured **card** (Pillar 2) and span excerpts.
3. **Citation usage map** *(your reverse index — a payoff of going relational)* —
   pick a paper, see **every place it is cited in your text** (project → manuscript
   section/line, from `citation.manuscript_loc`) **and every branch/experiment that
   uses it** (from `evidence`→`log_entry`/`run`). One paper → all its downstream
   uses, across writing and experiments.
4. **Branch explorer** — the interactive experiment DAG (`experiment.parent_id`
   edges); click a node → its config, runs, metrics, artifacts, and linked papers.
5. **Timeline / notes** — decision log + meeting notes over time, filterable by type.

This adds one field to the schema: `citation.manuscript_loc` (project + section +
line/label) records *where in your draft* a cite appears, distinct from the
`start/end` span into the *source* paper — together they power the reverse map.
Stack is deferred ("wait with that"); the views above are stack-independent.

---

## Pillar 1 — Ingest

**Purpose.** Turn an external artifact (PDF / arXiv id / DOI / URL) into a
first-class, identified, deduplicated entry in the shared library with
bibliographic metadata. Today `library/` is flat `.txt` files with no record of
what a paper *is*.

**Layout (promote the flat corpus to per-paper records via sidecars):**
```
library/
  <key>.pdf|.txt|.md          the source  (key = surname+year+slug, e.g. gao2023_alce)
  <key>.paper.json            bibliographic metadata sidecar           ← NEW
```

**`<key>.paper.json` schema:**
```json
{
  "key": "gao2023_alce",
  "title": "Enabling Large Language Models to Generate Text with Citations",
  "authors": ["Tianyu Gao", "Howard Yen", "..."],
  "year": 2023,
  "venue": "EMNLP",
  "doi": "10.18653/v1/2023.emnlp-main.398",
  "arxiv_id": "2305.14627",
  "url": "https://arxiv.org/abs/2305.14627",
  "sha256": "7479b4ef…",
  "added": "2026-06-30",
  "tags": ["citation", "attributed-qa"],
  "bibtex_key": "gao2023alce"
}
```

**Acquisition is stdlib-only.** Metadata auto-fills from the arXiv Atom API or
the Crossref REST API (both via `urllib`, no new deps). LLM extraction from the
first page is an `--extra api` upgrade for sources with no DOI/arXiv id.

**CLI (extends `reref/cli.py`):**
- `reref add <pdf|arxiv-id|doi|url>` — copy/fetch source into `library/`, derive
  `key`, fetch metadata, write sidecar, dedup by sha256, then auto-`index`.
- `reref bib` — emit `references.bib` for the whole corpus from the sidecars
  (this is what wires Pillar 3 citations into the LaTeX of Pillar 6).

**Build tasks:** `reref/ingest.py` (acquire + metadata + dedup), Crossref/arXiv
clients, sidecar read/write, `reref add`/`reref bib` commands, migrate the two
demo papers to sidecars.

---

## Pillar 2 — Knowledge base (retrieve + **structured extraction**)

**Purpose.** Two distinct capabilities. (a) *Retrieval* — already works (the
`.reref` index). (b) *Structured extraction* — distill each paper once into a
machine-readable **card** so you can "directly extract information," not just
retrieve raw spans. This is the missing half.

**Layout (derived → lives under `.reref/`):**
```
.reref/
  reref.index.json            EXISTS — passage vectors + offsets
  reref.lock.json             EXISTS — reproducibility pins
  cards/<key>.json            NEW — one structured card per paper
```

**Card schema — every field value carries its own span anchor**, so the card is
itself citable (the card never becomes a second, un-sourced copy of the paper):
```json
{
  "key": "gao2023_alce",
  "problem":      {"text": "LLMs generate fluent but unverifiable text…", "anchor": {"start": 120, "end": 240, "quote": "…"}},
  "method":       {"text": "ALCE benchmark: citation precision/recall via NLI", "anchor": {...}},
  "contributions": [ {"text": "…", "anchor": {...}} ],
  "results":      [ {"text": "…", "anchor": {...}} ],
  "limitations":  [ {"text": "…", "anchor": {...}} ],
  "extracted_by": "heuristic|llm", "model": null, "generated": "2026-06-30"
}
```

**Two backends, same schema.** Default (stdlib): section-heading + cue-phrase
heuristics over the parsed text — coarse but free. Upgrade (`--extra api`):
schema-constrained LLM extraction. Either way each field is re-anchored through
the existing `selectors.py`, so cards stay version-robust like citations.

**CLI:** `reref card <key>` (show/generate), `reref extract [--all]` (build cards
for the corpus), `reref ask "<question>" [--key <key>]` (RAG answer that returns
card fields + span citations rather than loose chunks).

**Build tasks:** `reref/extract.py` (heuristic + LLM backends), card store,
re-anchor card fields via `selectors`, `card`/`extract`/`ask` commands. Also:
default retrieval is TF-IDF (weak); wire the already-scaffolded
`Qwen3`/`BGE-M3` embedder as the recommended `--extra` once on a torch-capable box.

---

## Pillar 3 — Cite  ✅ (built; finish-work only)

**Status.** Complete on demo: `retrieve → anchor (W3C TextQuote) → verify
(full/partial/none) → \spancite + citations.json`, reproducible via the lockfile
and per-citation `source_sha256` + quoted text.

**Remaining finish-work (no redesign):**
- Wire the verified SOTA backends end-to-end on one real run: Docling parse →
  Qwen3 embed → LongCite/FactCG verify (see `sota-citation-stack` memory).
- Make `citations.json` ⇄ `references.bib` consistent: every cite's `source_id`
  resolves to a `bibtex_key` from a Pillar-1 sidecar, so `\spancite` and the
  bibliography reference the same entry.

---

## Pillar 4 — Ideate

**Purpose.** Give ideas a structured, corpus-linked home so positioning against
prior art is a living artifact, not prose you re-argue each time. Today
`ideation.md` is freeform.

**Layout (per project):** `projects/<name>/ideation.md` from a fixed template:
```
# <Project title>
## Problem            (what's broken, who cares)
## Core idea          (the mechanism)
## Contributions      (numbered, dependency-ordered)
## Positioning        ← table: prior-art row → library key → how we differ
## Thesis             (one testable claim)
## Evaluation plan    (dataset / baselines / metrics — design before building)
## Open questions     (parked risks)
```

The **Positioning** table cites library keys directly, so
`reref card <key>` pulls the structured summary of each competitor inline. The
existing `novelty-verdict` memory is exactly one filled-in Positioning section —
this pillar makes that a repeatable workflow.

**CLI:** `reref new <project>` scaffolds the project (ideation template + dirs +
`git init` + experiment/log skeleton).

**Build tasks:** project template, `reref new`, a `reref positioning <project>`
helper that resolves the cited keys to cards.

---

## Pillar 5 — Experiment + reasoning log  🔴 (your stated pain point — biggest gap)

**Purpose.** A sequenced, reproducible record of *what you did, in what order,
and why* — so progress is legible, decisions are recoverable, and results are
never hallucinated because they only ever come from a logged run.

**Storage.** Experiment records, configs, runs, metrics, and log entries are
**rows in the core SQLite DB** (see Core architecture) — that is what makes the
DAG, configs, and results queryable and cross-linkable. Only large/opaque outputs
live on disk:
```
projects/<name>/
  runs/<run-id>/                  on-disk artifacts only (figures, checkpoints, CSVs)
  src/                            the experiment code (entrypoints)
  # experiment / config / run / metric / log_entry rows  ─▶  .research/env.db
  # prose (rationale, notes)      ─▶  log_entry.body_md / note.body_md columns
```

**`experiment` + `config` + `run` rows (the state machine, normalized):**
```jsonc
// experiment
{ "id": "002-qwen3-embed", "project_id": 1, "parent_id": "001-tfidf-baseline",  // parent = DAG edge
  "title": "Swap TF-IDF for Qwen3 embeddings",
  "hypothesis": "Dense retrieval raises citation recall on the eval set",
  "status": "planned|running|done|abandoned", "created": "2026-06-30T14:20:00Z" }
// config (one row, reused by many runs — your "config from another table")
{ "id": 7, "params_json": {"embedder": "Qwen3-0.6B", "top_k": 5, "seed": 0} }
// run (pins reproducibility)
{ "id": 31, "experiment_id": "002-qwen3-embed", "config_id": 7,
  "git_sha": "abc123", "corpus_lock_hash": "…", "started": "…", "finished": "…" }
// metric rows (sole home of every number)
{ "run_id": 31, "name": "citation_recall", "value": 0.82 }
```

**`log_entry` (prose in `body_md`, typed, linked via `evidence`):**
```
type ∈ {decision, hypothesis, observation, result, blocker}
body_md: "## Anchor at sentence granularity\nsub-sentence anchors underperformed…"
evidence: [{run_id: 28}, {citation_id: 12}]      ← a `result` entry MUST link a run
```

**Anti-hallucination mechanics (now DB-enforced, not aspirational):**
1. Paper numbers are generated from `metric` rows — a results table is a *query
   output*, never typed (ties to Pillar 6).
2. A `result` `log_entry` with no `evidence`→`run` is rejected by a DB constraint —
   stronger than the earlier CLI check.
3. Session restore = query the DAG + the latest `log_entry` rows, so the agent
   (via MCP) can't lose the thread of what was already tried.

**CLI (thin wrappers over the engine + DB; the same code paths the MCP server and
web cockpit call):**
- `reref exp new <project> "<title>" [--parent NNN]` — insert experiment row + scaffold `src/` entrypoint.
- `reref exp run <project> NNN` — execute entrypoint, capture `metrics` rows + on-disk `artifact`s, flip status, insert a `result` `log_entry`.
- `reref exp list <project>` — render the DAG + statuses (the progress view).
- `reref log <project> "<text>" --type decision [--evidence run:28,cite:12]`.

**Build tasks:** `reref/db.py` (schema + migrations + deterministic export),
`reref/experiment.py` (scaffold/run/state over the DB), `reref/log.py` (append +
constraint), `exp`/`log` command group, the DAG renderer.

---

## Pillar 6 — Write (paper template + assembly)

**Purpose.** Draft fast and keep the manuscript honest: it *references* citations
and experiment results rather than duplicating them.

**Layout (per project):**
```
projects/<name>/text/
  paper.tex                    template: abstract→intro→related→method→exp→results→concl
  preamble.tex                 \spancite macro (from `reref preamble`)
  references.bib               generated by `reref bib` (Pillar 1)
  results_table.tex            GENERATED from experiments/*/results/metrics.json
```

**Assembly, not retyping:**
- `\spancite{key}{start}{end}{quote}` is fed from `citations.json`.
- `reref weave <project>` regenerates `results_table.tex` from every experiment's
  `metrics.json`, so paper numbers are a build output of Pillar 5 — they cannot
  drift from what was actually run.
- Markdown variant (`paper.md`) for early drafting; same citation/result hooks.

**CLI:** `reref draft <project>` (scaffold `text/` from template),
`reref weave <project>` (regenerate generated `.tex` from citations + metrics).

**Build tasks:** LaTeX/MD templates, `draft`/`weave` commands, the metrics→table
generator, citations.json→`\spancite` emitter (extends existing `cite.py`).

---

## Pillar 7 — Orchestrate (the "auto" layer)

**Purpose.** Encode the operating protocol so an agent (or you) drives Pillars
1→6 under the §0 invariant. Today `AGENTS.md` is a one-line stub — this is what
turns a pile of tools into an *environment*.

**`AGENTS.md` becomes the enforced protocol:**
1. **Restore context first.** Read the project's `LOG.md` tail + `reref exp list`
   before doing anything in a project.
2. **Source every claim.** A statement about the literature → `reref cite` it. A
   statement about a result → it must come from an experiment run. No exceptions.
3. **Log before you pivot.** Any change of direction is a `[decision]` entry with
   a `Why:` and evidence links *before* the work, not after.
4. **Results are generated, never typed.** Use `reref weave`; never hand-write a
   number into the paper.
5. **One experiment, one question.** New hypothesis → `reref exp new`, don't mutate
   a finished experiment.

**The MCP server is the mechanism that lets an agent execute this protocol.** A
local stdio MCP server (`reref-mcp`) exposes the engine + DB as tools so Claude
Code drives the research directly — it is the third client over the one store
(see Core architecture), alongside the web cockpit and the CLI. Tools:

| Tool | Does | Pillar |
|---|---|---|
| `search_papers` / `retrieve_spans` | RAG over the corpus | 2 / 3 |
| `get_card` | structured extraction of a paper | 2 |
| `cite_claim` | anchor + verify a claim → span + support level | 3 |
| `list_experiments` / `get_experiment` | walk the DAG | 5 |
| `record_run` / `get_metrics` | write/read experiment results | 5 |
| `log_decision` / `add_note` | append prose (constraint-validated) | 5 |
| `query` | read-only SQL / NL over the whole env | all |
| `review_section` | per-section critique | 8 |

Read tools are unrestricted; write tools (`record_run`, `log_decision`, …) go
through the *same* engine code paths as the CLI, so the §0 DB constraints apply no
matter which client calls them. **Implemented (Phase B):** `reref/mcp_server.py`
is a pure-stdlib stdio server (newline-delimited JSON-RPC 2.0) — **zero extra
dependencies**, no SDK — exposing `status`, `search_corpus`, `cite_claim`,
`create_project`, `create/list/get/run_experiment`, `log_decision`, `list_log`,
`check_invariants`, `add_note`, `register_dataset`, and a read-only `query`. Run
via `reref mcp`; registered in `.mcp.json` so it loads in Claude Code. (`get_card`
/ `review_section` land here once Pillars 2 / 8 exist.)

**Optional:** a few project-scoped skills/slash-commands wrapping the common
loops (`/ideate`, `/run-next-exp`, `/draft-section`).

**Build tasks:** rewrite `AGENTS.md` (the protocol); `reref/mcp_server.py` +
`.mcp.json` registration; optional `.claude/` commands; a `reref status <project>`
that reports protocol compliance (uncited claims, results with no run link).

---

## Pillar 8 — Critique (per-section agentic review)  🔴 (new requirement)

**Purpose.** A fine-grained, agentic feedback loop that audits a draft
**section-by-section against an explicit rubric of individual checks** — not one
manual big sweep. It surfaces specific, located, falsifiable issues and, where
possible, *mechanically verifies* them against the rest of the system (citations,
metrics) rather than relying on the model's opinion. This is distinct from Pillar
6: writing produces the draft, critique evaluates and improves it.

**The rubric is the heart of it** — checks are data, not prose. `reref/rubric/`
holds a versioned set of section → check definitions:
```yaml
# reref/rubric/default.yaml
sections:
  abstract:
    - id: abs-claim-matches-results
      dimension: correctness
      check: "Does every quantitative claim in the abstract match a `metric` row from a run?"
      verify: automated            # cross-checked against metrics, not judged
      severity: high
    - id: abs-contribution-explicit
      dimension: completeness
      check: "Are the contributions stated as a concrete, enumerable list?"
      verify: llm
      severity: medium
  related_work:
    - id: rw-positioning-explicit
      dimension: novelty
      check: "Is the delta vs. each cited prior work stated, not just summarized?"
      verify: llm
      severity: high
    - id: rw-cites-verify
      dimension: correctness
      check: "Does every \\spancite resolve to a span that *fully* supports the sentence (reref verify == full)?"
      verify: automated
  method: [ reproducible, notation-defined, assumptions-stated, … ]
  experiments: [ baselines-present, ablations, hyperparams-reported, seeds, … ]
  results: [ claims-trace-to-metrics, stats-significance, no-cherrypick, … ]
  # …intro, discussion, conclusion, limitations
```
Each check has a **dimension** (clarity / correctness / completeness / rigor /
novelty / reproducibility) and a **verify mode**: `automated` checks run through
`reref` (citation support, metric matching) and are deterministic;
`llm` checks are judged by a subagent. The MECE-ness lives here — every section ×
dimension cell is either covered by a check or explicitly empty.

**Agentic pipeline (Claude Code Workflow — fan-out, verify, synthesize):**
```
parse paper into sections
  └─ for each (section × dimension) cell:                 ── pipeline, no barrier ──
       finder agent  → structured findings {check_id, location, issue, severity, fix}
       verifier agent → adversarially confirm each finding is real (kill false positives)
  └─ synthesize → reviews/<date>.md  (+ optional inline \todo{} in the .tex)
```
Findings are structured, located (section + line/span), and each carries a
suggested fix. The **verify pass is adversarial** — a second agent tries to refute
each finding, so the report is high-signal, not a wall of nitpicks. Automated
checks need no judge: an abstract number with no matching `metric` row is
a fact, not an opinion.

**Finding schema:**
```json
{
  "check_id": "abs-claim-matches-results",
  "section": "abstract",
  "location": {"line": 4, "quote": "improves recall by 12%"},
  "severity": "high",
  "issue": "‘12%’ has no match in any experiments/*/results/metrics.json",
  "fix": "Regenerate via `reref weave`, or run the experiment that produces this number",
  "verified": true, "verify_mode": "automated"
}
```

**Re-runnable → quality is tracked over time.** Each run writes
`projects/<name>/reviews/<date>.md`; a `reref review --diff` shows which findings a
revision resolved or introduced. A clean run is a release gate.

**CLI / invocation:**
- `reref review <project> [--section method] [--rubric default]` — emits the
  review report (drives the Workflow internally, or prints the agent plan when run
  outside an agent).
- Ships as a Claude Code skill/command (`/review-paper`) so you run it inside
  Claude Code with the fan-out pipeline; the deterministic `automated` checks also
  run standalone from the CLI without any model.

**Build tasks:** `reref/rubric/default.yaml` (the check library), section splitter,
`reref/review.py` (run automated checks standalone + assemble findings), the
Workflow script for the agentic fan-out/verify/synthesize, `reref review` command
+ `/review-paper` skill, report renderer + `--diff`.

**Leverages the whole system.** The high-value checks are the *automated* ones,
and they only exist because Pillars 3 and 5 give the reviewer ground truth:
citations that `verify`, and metrics that are the sole home of every number. A
review agent without those is just another opinion; with them it's a checker.

---

## Cross-cutting: where each pillar's state lives

| Kind | Location | Tracked by git? |
|---|---|---|
| Engine + templates | `reref/`, `docs/`, templates | research-env repo |
| Source papers | `library/*` | ignored (personal corpus) |
| Derived (index, cards) | `.reref/*` | ignored (regenerable) |
| A paper you're writing | `projects/<name>/*` | its **own** repo |

Consistent with the existing git strategy in the `reref-architecture` memory.

---

## Phased build plan

Sequenced by leverage and dependency, not by pillar number.

- **Phase A — Experiment + reasoning log (Pillar 5).** Standalone, highest
  leverage, your stated pain point. Delivers `reref exp` + `reref log` and the
  per-project skeleton. *No dependency on the others.*
- **Phase B — Orchestration spine (Pillar 7).** Rewrite `AGENTS.md` to enforce the
  §0 invariant over Phase A. Cheap, compounds everything after it.
- **Phase C — Ideate + Write (Pillars 4 & 6).** `reref new` / `reref draft` /
  `reref weave` + templates. Makes the project workspace end-to-end usable.
- **Phase D — Ingest + Knowledge base (Pillars 1 & 2).** `reref add` / `reref
  card` / `reref extract` — promote `library/` to a real paper DB with metadata
  and structured extraction. Heaviest; benefits from being last so the consumers
  (cards in Positioning, bib in Write) already exist.
- **Phase E — Critique (Pillar 8).** The per-section agentic review agent. Slots
  here because its highest-value (automated) checks depend on Cite (3) and
  Experiment (5) being real, and on Write (6) producing a draft to review. The
  `automated` checks ship as plain CLI; the `llm` fan-out ships as a Claude Code
  skill/Workflow.
- **Phase F — Cite finish-work (Pillar 3).** Wire SOTA backends + bib consistency
  on a torch-capable box.

Each phase ships working CLI + tests, stdlib-first, SOTA backends as `--extra`.
```
```
