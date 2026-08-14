# Autonomous-scientist landscape vs renv

Snapshot: **14 August 2026**. Star counts and licenses are from GitHub on that date
and will drift. This is product landscape documentation — not research graph
state, not a second copy of claims.

**How to read it.** Almost every system below *emits papers* (or reports). renv
is a **research OS**: it refuses ungrounded writes. Overlap is therefore
narrower than the marketing category “AI scientist” suggests. The interesting
question is which of their *mechanisms* we already enforce, which we should
steal as store-native features, and which would violate the architecture in
[`AGENTS.md`](../AGENTS.md).

**Scope.** Public repos and named systems that run an autonomous (or
heavily agentic) research loop: ideation → literature → experiment →
manuscript. Adjacent literature engines and lab/PKM tools are listed last so
they are not mistaken for peers.

---

## Positioning

| | Typical AI scientist | renv |
|---|---|---|
| Product | A pipeline that writes a paper | A local-first store that an agent (or human) must write *through* |
| Success metric | Workshop/conference-looking PDF; leaderboard score | Every claim shows its work |
| Numbers enter via | LLM prose, cherry-picked logs, or a writer node | A recorded `run` → `metric` row → `renv weave` |
| Literature enters via | RAG snippets, Semantic Scholar, model memory | Span-anchored `citation` with a verifier verdict |
| Status | The agent asserts “we showed X” | Derived from linked evidence; open until backed |
| Second store | `ideas.md`, `program.md`, `answer.md`, YAML notes, Neo4j | Forbidden. Markdown is protocol; the SQLite store is state |
| Evidence in the PDF | Intermediate tags, then stripped | `\spancite` stays in the manuscript |
| LLM in the engine | Writer, reviewer, judge, tree-search | Not in `renv/research/`. Optional extras (FactCG, embeddings) sit behind lazy imports |

Closest cousin is Google Cloud AI’s **ScientistOne** (Meng et al.,
[arXiv:2605.26340](https://arxiv.org/abs/2605.26340),
[scientist-one.github.io](https://scientist-one.github.io/)): they also treat
claim-to-evidence as a first-class constraint. They still *generate* the paper,
keep evidence tags in an intermediate markdown representation, then **Compose
into LaTeX without those tags**. Integrity checks I2 and I4 are majority-vote
LLM judges. No public code.

---

## Capability matrix

Legend for the **renv** column:

- **yes** — on `main` (this snapshot: `ae77fb8`)
- **thin-client gap** — domain function exists; CLI (or MCP) surface missing or incomplete
- **PR** — implemented in an open PR, not yet on `main`
- **no** — not built
- **refuse** — out of scope on purpose

| Capability | Typical AI-scientist move | renv |
|---|---|---|
| Span-anchored citation (quote + offsets, not a chunk id) | Rare. RAG snippets or `\cite{key}` | **yes** — `renv cite` / MCP `cite_claim`; W3C TextQuoteSelector |
| Refuse `support=none` on write | Almost never. Writer emits the cite | **yes** — refused without `--force` |
| Keep evidence tags in the published manuscript | ScientistOne tags then Compose-strips; others never tag | **yes** — `\spancite{key}{start}{end}` |
| Claim graph with derived status | ScientistOne CoE tags; most have none | **yes** — `claim add/link/relate`; status from evidence |
| Pre-register “this experiment tests that claim” | Curie-style plans; ScientistOne PI brief | **thin-client gap** — `declare_test` on MCP + cockpit; CLI in [PR #30](https://github.com/julianwinking/renv/pull/30) |
| Experiment DAG (branch, don’t mutate) | AIDE/ASv2 tree search over code; Curie partitions | **yes** — `exp new --parent`; one experiment, one question |
| Pinned runs (`git_sha`, env hash, seed, `metrics.json`) | Mixed. Many log to files the writer then quotes | **yes** — `exp run` / `exp ingest`; provenance `complete` / `remote` / `remote-verified` |
| Numbers only from metric rows | Writer copies a score; ASv2 writer can cherry-pick a non-submitted node | **yes** — weave `results_table.tex`; `result` log entries need a run (`log check`) |
| Bind the manuscript to one `run_id` (anti cherry-pick) | Generally absent; ASv2 known failure | **no** |
| Re-run the submitted artifact vs claimed score (ScientistOne I1) | Curie reproducibility; ScientistOne I1 | **no** — no `exp recheck` |
| Bibliography *exists* in the local bib | Common | **yes** — review `bib-coverage` vs `references.bib` |
| Bibliography *exists in the world* (Crossref / S2 / OpenAlex) | ScientistOne I3 | **PR** — `bib-known-paper` in [PR #28](https://github.com/julianwinking/renv/pull/28) (local paper table, not live API) |
| Method section vs code (ScientistOne I4) | LLM majority vote | **no** — and **refuse** LLM-as-judge; AST/regex lint would be in-scope |
| Graph lints (unbacked thesis, none-verdict support, exploratory-only, …) | Absent | **thin-client gap** — `lint.run` via MCP `check_invariants` + cockpit; CLI in PR #28 |
| Automated manuscript review (numbers ↔ metrics, `\spancite` ↔ full) | LLM reviewer (ASv2, CycleResearcher) | **yes** — `renv review`; `--strict` + non-waivable findings in PR #28 |
| Paper highlights join the graph | PDF readers / YAML notes | **thin-client gap** — `paper_note` in cockpit; CLI/MCP `annotate` in PR #30 |
| Shared corpus index, queryable as text | PaperQA2, STORM retrieval, PaSa | **yes** — `renv index` + `cite`/`resolve`/`search_corpus`; store FTS is a *second* surface (`renv search`) |
| Traffic-light a paper’s own bibliography vs the corpus | Rare | **yes** — `references build\|list\|add\|mark` |
| LLM paper writer as the product | The whole category | **refuse** |
| Agentic tree search over experiments | ASv2 AIDE, ScientistOne Discovery Engine | **refuse** as engine code; an agent may branch `exp new --parent` itself |
| Markdown/YAML as research state | Karpathy `program.md`, InternAgent `answer.md`, AgentLaboratory notes | **refuse** |
| Wet-lab / chemistry tools | Coscientist, ChemCrow, Robin, Virtual Lab | **out of scope** (OS is domain-agnostic) |
| Multi-agent PI / scientist / reviewer roles | Virtual Lab, InternAgent, AgentLaboratory | **refuse** as engine; protocol lives in `AGENTS.md` |

---

## Critical overlap

Three clusters matter. Everything else is a paper mill, a retrieval engine, or
a lab-specific tool.

### 1. Evidence-aware paper mills (closest cousins)

**ScientistOne** is the only system that shares renv’s *diagnosis*: autonomous
pipelines fail because claims are not traced to evidence, and surface review
cannot see that. Their CoE Integrity Audit (75 papers, five systems) is the
best public measurement of the failure mode renv is built to prevent:

| Check | ScientistOne result | What renv already does | Gap |
|---|---|---|---|
| **I1 Score verification** — re-run submitted code, compare to the paper’s number | 12/12 | Weave + `abs-claims-match-metrics` (prose token vs metric *value*). Does **not** re-execute | `exp recheck`; bind manuscript to one `run_id` |
| **I2 Spec violation** — code cheats the evaluator | 0/15; **LLM majority vote** | Nothing domain-specific | Stay out unless a project registers a golden evaluator as a dataset + run |
| **I3 Reference verification** — bib entry resolves in S2/arXiv/OpenAlex/Crossref | 0/337 hallucinated | Local: span cites cannot be invented (they must hit indexed text); `bib-coverage` is file-local; paper table exists after `renv add` | Live API existence check; retraction / expression-of-concern column |
| **I4 Method–code alignment** | 14/15; **LLM majority vote** | `@renv` code tags (`refs scan/check`) are the opposite direction (code → store), not method prose → AST | Deterministic method–code lint, not an LLM judge |

**Do not steal from ScientistOne:** stripping evidence tags before the PDF;
LLM-as-judge of numbers or of “does this paragraph match this file”; generating
the paper as the product; treating 98% “numerical CPR” as a substitute for
span anchors.

**Steal (fits invariants):** never drop `\spancite`; re-execution vs claimed
score as a *run*; bib existence as a review check (PR #28 starts this locally);
method–code alignment via AST/regex against the method section, written as
lint findings.

Independent eval of **AI Scientist v1** ([arXiv:2502.14297](https://arxiv.org/abs/2502.14297)):
hallucinated numbers, ~42% of experiments failed. ASv2’s writer has been
observed cherry-picking ablation scores from a tree node that was not the
submitted artifact. renv’s weave + `results-table-fresh` exist specifically
so that path is harder; they are not yet a bind-to-`run_id` guarantee.

### 2. Experiment operating systems (real overlap, different product)

**Curie** ([Just-Curieous/Curie](https://github.com/Just-Curieous/Curie),
Apache-2, ~367★) is the closest *experiment-OS* peer: a partition DAG,
reproducibility checks, “did the experiment actually run.” That maps onto
renv `experiment` + `run` + `log check`, not onto a writer.

**Karpathy/autoresearch** (~93k★) is a single-GPU training loop with
`program.md` as the living spec — exactly the “second store” renv forbids.
The *idea* (an agent that only mutates an experiment under a budget) is an
agent policy on top of `exp run`, not an engine feature.

**InternAgent** uses Claude Code as a lab backend and writes `answer.md`.
renv already *is* that backend (MCP). The file is the anti-pattern.

### 3. Literature engines (necessary, not sufficient)

**PaperQA2**, STORM, PaSa, OpenScholar, ScholarQA, Elicit, Consensus, Scite
answer questions from papers. renv’s corpus index + `cite` is the write-path
version of that: retrieval is allowed; a claim is not supported until a span
verifies. Do not import their consensus meters or “the literature says” UX
as claim status.

---

## Catalog — autonomous / agentic research systems

Each entry: what it is, overlap with renv, what they have that we do not, what
to refuse. Stars as of this snapshot.

### End-to-end paper generators

#### ScientistOne (Google Cloud AI Research)

- **Code:** none public. Site: [scientist-one.github.io](https://scientist-one.github.io/). Paper: [arXiv:2605.26340](https://arxiv.org/abs/2605.26340)
- **What:** PI (≤100 PDFs → experiment brief) → Discovery Engine (explore/exploit tree) → Paper Writer with intermediate evidence tags → Compose LaTeX. Post-hoc CoE audit I1–I4.
- **Overlap:** claim-to-evidence as architecture; score must match an artifact; bib must exist.
- **They have, we don’t:** automatic paper generation; tree-search solver; I1 re-execution; I3 live bibliographic APIs; I4 method–code check.
- **We have, they don’t:** span anchors that survive into the PDF; a durable project graph (claims, log, notes, DAG) that is not thrown away after Compose; refuse-`none`; human cockpit; local-first store.
- **Refuse:** LLM majority-vote integrity; stripping tags.

#### The AI Scientist v1 — [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist)

- **~14.4k★**, license: RAIL / Other. Paper: Lu et al. 2024.
- **What:** template ML repo → ideation → code → experiment → write → LLM reviewer. Fully automated open-ended discovery as the pitch.
- **Overlap:** experiment + manuscript in one loop. That is the *category*, not the mechanism.
- **They have, we don’t:** LLM writer and reviewer; template-driven code edit.
- **We have, they don’t:** every row of the matrix above that is “yes”.
- **Refuse:** generating papers from templates; LLM review as a gate; executing model-written code inside the engine.

#### The AI Scientist v2 — [SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2)

- **~7.0k★**, license: Other. Paper: [arXiv:2504.08066](https://arxiv.org/abs/2504.08066). Workshop-level papers via **AIDE** best-first tree search.
- **Overlap:** branching experiments ≈ renv DAG. Integrity audit (ScientistOne table): I1 5/12 (42%), I3 0/159 hallucinated refs, I4 5/15 (33%, confounded by scaffolding).
- **They have, we don’t:** BFTS over code; LLM review-aware reporting.
- **Known failure:** writer can report a node that is not the submitted run. renv weave reduces this; bind-to-`run_id` would close it.
- **Refuse:** tree search in-engine; LLM reviewer.

#### Agent Laboratory — [SamuelSchmidgall/AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)

- **~5.8k★**, MIT. Human-in-the-loop “assist you toward implementing your ideas.” YAML notes; **AgentRxiv** for agent-to-agent papers.
- **Overlap:** phased workflow (lit → plan → experiment → write) similar to renv’s operating loop, implemented as agents + files.
- **They have, we don’t:** packaged multi-agent roles; AgentRxiv.
- **Refuse:** YAML/markdown as ground truth. A `feedback` log entry with `--source` is the renv equivalent of human steering.

#### AI-Researcher — [HKUDS/AI-Researcher](https://github.com/HKUDS/AI-Researcher)

- **~5.7k★**, license not declared on GitHub. NeurIPS 2025; hosted at [novix.science](https://novix.science/chat).
- **Overlap:** end-to-end innovation pitch. ScientistOne audit: I1 9/12, I3 21/222 hallucinated (9.5%), I4 12/15 (best baseline on method–code).
- **They have, we don’t:** production chat UI that *does* the research.
- **Refuse:** the product shape (chat that emits papers). renv’s cockpit is an audit surface, not a writer.

#### InternAgent — [InternScience/InternAgent](https://github.com/InternScience/InternAgent)

- **~1.4k★**, Other. “Long-horizon autonomous scientific discovery”; Claude Code as lab backend; `answer.md` as working memory.
- **Overlap:** MCP/CLI agent driving experiments — renv *is* that backend.
- **Refuse:** `answer.md` as a second store. Put the answer in a `log` entry (and a claim, if it is a claim).

#### CycleResearcher — [zhu-minjun/Researcher](https://github.com/zhu-minjun/Researcher)

- **~400★**. Paper: “Improving Automated Research via Automated Review.”
- **Overlap:** review-in-the-loop. renv already has `review` + findings adjudication; the difference is automated checks vs an LLM reviewer that also rewrites the paper.
- **Refuse:** LLM-rewrite-until-the-reviewer-is-happy as a substitute for store invariants.

#### AutoResearchClaw

- **Paper:** [arXiv:2605.20025](https://arxiv.org/abs/2605.20025) (Liu et al. 2026). Appears in the ScientistOne 75-paper audit (ARC): I1 5/12, I3 3/196 (1.5%, including a hand-curated YAML “seminal papers” file that injects a wrong title), I4 3/15.
- **Lesson for renv:** a curated YAML library of “important papers” is a hallucination factory. `renv add` + indexed text is the antidote; never cite from a sidecar list that is not the corpus.

#### DeepScientist

- Named in the ScientistOne audit (strong I1 11/12, worst I3 20.9% hallucinated refs). Public code not confirmed in this snapshot. Same lesson: solver quality ≠ bibliography integrity.

#### Zochi — [IntologyAI/Zochi](https://github.com/IntologyAI/Zochi)

- **~312★**. Intology’s autonomous researcher. Paper-mill shape; not an OS.

#### EvoScientist — [EvoScientist/EvoScientist](https://github.com/EvoScientist/EvoScientist)

- **~4.6k★** (+ EvoSkills). “Vibe research” / self-evolving AI scientists. Skills packs are the opposite of a single store: behavior lives in installable prompts.
- **Overlap with renv:** none that we want. `AGENTS.md` is the protocol; it is not a skill marketplace.

#### PaperBanana — [dwzhu-pku/PaperBanana](https://github.com/dwzhu-pku/PaperBanana)

- **~6.9k★**. Automates *illustrations* for AI-scientist papers. Orthogonal. renv does not generate figures; runs may emit artifacts, which are not citable (TELESCOPE).

### Experiment / code-discovery agents

#### Curie — [Just-Curieous/Curie](https://github.com/Just-Curieous/Curie)

- **~367★**, Apache-2. Paper: [arXiv:2502.16069](https://arxiv.org/abs/2502.16069). EXP-Bench: [arXiv:2505.24785](https://arxiv.org/abs/2505.24785).
- **What:** automated experimentation with partition DAGs and reproducibility checks (ScientistOne analogizes this to I1).
- **Overlap:** this is the nearest experiment-OS. renv already has DAG, pinned runs, ingest, remotes, `log check`.
- **Steal as a *view*:** Curie’s partition diagram is a presentation of the experiment DAG (cockpit already has a graph). Do not store partitions as a second tree.
- **They have, we don’t:** an experiment-reproduction benchmark (EXP-Bench) as a first-class eval; tighter “did this code satisfy the protocol” checks.

#### AIDE — [WecoAI/aideml](https://github.com/WecoAI/aideml)

- **~1.5k★**, MIT. LLM agent for ML engineering; used inside ASv2; cited in OpenAI MLE-bench.
- **Overlap:** none in the store. An agent using renv could call AIDE *as the experiment entrypoint* and ingest `metrics.json`. Do not vendor AIDE.

#### CodeScientist — [allenai/codescientist](https://github.com/allenai/codescientist)

- **~347★**, Apache-2. Ideation grounded in literature *and* code.
- **Overlap:** renv already joins papers to experiments via claims + `@renv` tags. CodeScientist’s joint ideation is an agent strategy (`discover` + `cite` + `exp new`), not an engine.

#### ASI-Arch — [GAIR-NLP/ASI-Arch](https://github.com/GAIR-NLP/ASI-Arch)

- **~1.2k★**. Autonomous neural architecture search framed as scientific discovery.
- **Overlap:** a specialized solver. Register results as runs; do not absorb NAS into renv.

#### karpathy/autoresearch — [karpathy/autoresearch](https://github.com/karpathy/autoresearch)

- **~93.8k★**, license undeclared. Single-GPU nanochat training, agent-edited.
- **Overlap:** budgeted experiment loop.
- **Refuse:** `program.md` as the spec. The spec is `RENV_PARAMS` + git sha + a hypothesis claim.

#### MLR-Copilot — [du-nlp-lab/MLR-Copilot](https://github.com/du-nlp-lab/MLR-Copilot)

- **~70★**. ML research copilot (idea → experiment assistance). Copilot, not OS.

#### OpenClaudeScience — [qzzqzzb/OpenClaudeScience](https://github.com/qzzqzzb/OpenClaudeScience)

- **~92★**. Claude-driven science loop. Same shape as InternAgent: the coding agent *is* the scientist; files are the store.

#### ARA / Agent-Native Research Artifact — [ARA-Labs/Agent-Native-Research-Artifact](https://github.com/ARA-Labs/Agent-Native-Research-Artifact)

- **~630★**. “Research ecosystem for rigorous and trustworthy AI scientists.” Artifact/packaging layer rather than a claim store. Watch for duplication of provenance files; renv already pins sha/env/seed on the run.

### Literature-first / report writers (not scientists)

These dominate GitHub stars and are routinely miscategorized as AI scientists.

| System | Repo | ★ | License | What it actually does | renv overlap |
|---|---|---|---|---|---|
| STORM | [stanford-oval/storm](https://github.com/stanford-oval/storm) | ~31.0k | MIT | Multi-agent Wikipedia-like report with citations | Discovery questions ≈ `log` type `question`. Citations are not span-verified. Do not generate reports into `text/` |
| GPT-Researcher | [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher) | ~29.0k | Apache-2 | Autonomous web/research reports, any LLM | Same: retrieval + write. No experiment DAG, no metrics |
| PaperQA2 | [Future-House/paper-qa](https://github.com/Future-House/paper-qa) | ~9.0k | Apache-2 | High-accuracy RAG over papers with citations | Closest *lit* engine. Steal: better PDF QA as an extra. Do not let a PaperQA answer become a supported claim without `cite` |
| OpenScholar | [AkariAsai/OpenScholar](https://github.com/AkariAsai/OpenScholar) | ~1.6k | | RAG-LM literature synthesis | Same as PaperQA2 |
| PaSa | [bytedance/pasa](https://github.com/bytedance/pasa) | ~1.6k | | Paper *search* agent (tools → read → follow refs) | Overlaps `discover` + `references add`. PaSa is a researcher; renv is where the chosen papers land |
| ScholarQA | [allenai/ai2-scholarqa-lib](https://github.com/allenai/ai2-scholarqa-lib) | ~280 | | Ai2 ScholarQA app/library | Lit QA. Asta / Semantic Scholar are query backends, not a store |
| ResearchAgent | [JinheonBaek/ResearchAgent](https://github.com/JinheonBaek/ResearchAgent) | ~54 | | NAACL 2025 — **ideation only** | Maps to `claim add --kind hypothesis` + questions. Stops before experiments |

**ResearchTown** — [ulab-uiuc/research-town](https://github.com/ulab-uiuc/research-town) (~210★). Simulated community of researchers. Fun; not an OS.

**SciAgents** — [lamm-mit/SciAgentsDiscovery](https://github.com/lamm-mit/SciAgentsDiscovery) (~631★). Ontology/graph-driven hypothesis generation (MIT LAMM). A `hypothesis` claim plus `cite` is the renv landing zone; do not import a Neo4j world model.

### Wet-lab, chemistry, biology

Out of renv’s domain. Listed so they are not treated as missing features.

| System | Repo / paper | ★ | Notes vs renv |
|---|---|---|---|
| Robin | [Future-House/robin](https://github.com/Future-House/robin) | ~665, Apache-2 | Multi-agent therapeutic discovery. Kosmos is the closed successor |
| Kosmos | Future House product; no public repo | — | Closed autonomous scientist for biology |
| Owl | Future House product; no public repo | — | Query/agent over literature — use as a *query*, not as claim status |
| Finch | [Future-House/finch](https://github.com/Future-House/finch) | ~94 | Notebook data-science agent on Aviary |
| Aviary | [Future-House/aviary](https://github.com/Future-House/aviary) | ~277, Apache-2 | Agent gym for scientific tasks |
| Coscientist | [gomesgroup/coscientist](https://github.com/gomesgroup/coscientist) | ~208 | Nature 2023 — LLM drives lab hardware |
| ChemCrow | [ur-whitelab/chemcrow-public](https://github.com/ur-whitelab/chemcrow-public) | ~946 | Chemistry tools for an LLM chemist |
| Virtual Lab | [zou-group/virtual-lab](https://github.com/zou-group/virtual-lab) | ~709, MIT | LLM PI + specialist agents; Nature 2025 nanobody work. Human phase gates ≈ renv `feedback` / `decision` |
| ToolUniverse | [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | ~1.6k | Tooling layer to “democratize AI scientists” |
| DiscoveryWorld | [allenai/discoveryworld](https://github.com/allenai/discoveryworld) | ~218 | **Benchmark environment**, not a scientist |

Google **co-scientist** (Nature / Google Research, 2025) is a closed multi-agent
system for biomedical hypotheses. Same category as Kosmos: no store we can
align to, no code to steal.

### Closed or paper-only (no repo to clone)

| System | Pointer | Why it is in this list |
|---|---|---|
| ScientistOne | [arXiv:2605.26340](https://arxiv.org/abs/2605.26340) | Closest philosophical cousin |
| Google co-scientist | Google Research 2025 | Closed biomedical multi-agent |
| Future House Kosmos / Owl / Crow | futurehouse.org | Productized PaperQA descendants |
| NovelSeek | ByteDance paper; no canonical public repo found this snapshot | End-to-end “seek novel ideas” mill |

---

## What renv already implements (mapped to surfaces)

This is the inventory the overlap column is judging against. **On `main`**
unless noted.

### Literature → span cite

| Surface | What it enforces |
|---|---|
| `renv add` / MCP `add_paper` | Identity invariant: file named `<key>.<ext>` |
| `renv index` | Shared corpus; cite/resolve retrieval |
| `renv cite` / `cite_claim` | Anchor + lexical verifier (FactCG extra); `support=none` refused without `--force` |
| `renv resolve` | Show the span without writing |
| `renv citation list\|rm` | Inspect; tombstones, never silent delete |
| `\spancite` + `renv preamble` | Evidence tag **in** the manuscript |
| `renv card` / `extract` | Structured paper cards (heuristic; quality varies) |
| `renv references *` | Parse a paper’s bibliography; traffic-light vs corpus; ingest → inbox |
| `renv inbox` | Human-unread papers. Agents must not `--read` |
| `renv discover` | arXiv keyword search |
| Cockpit Papers tab | PDF highlight → `paper_note` (CLI/MCP annotate: **PR #30**) |

### Claims → evidence

| Surface | What it enforces |
|---|---|
| `claim add` (`thesis` / `contribution` / `assertion` / `hypothesis`) | Claims are rows, not markdown |
| `claim link` / `link_claim_evidence` | Stance + grade; `none`-verdict cannot `supports` |
| `claim relate` (`depends_on` / `contradicts`) | Argument structure; does not set status |
| MCP `analyze_argument` | Foundation / contradiction / frontier (read-only) |
| `declare_test` (MCP + cockpit; CLI **PR #30**) | Pre-registration; post-hoc runs count as exploratory |
| `retract_evidence` / `confirm_evidence` | History-preserving retraction; stale-after-edit |

### Experiments → numbers → paper

| Surface | What it enforces |
|---|---|
| `exp new --parent` | DAG; one question per experiment |
| `exp run` | Entrypoint reads `RENV_RUN_DIR` / `RENV_PARAMS`, writes `metrics.json` |
| `exp ingest` + remotes | Cluster results; provenance never claimed `complete` if remote |
| `metric define` | Display registry (optional, never blocks a run) |
| `dataset add` | Version + sha256 (remote-capable) |
| `log add` + `log check` | `result` without a run is a §0 violation |
| `renv weave` | Regenerates `results_table.tex` + `references.bib` |
| `renv draft` / `new` | Scaffold from templates; ideation is store-native |

### Audit

| Surface | What it enforces |
|---|---|
| `renv review` | Automated: numbers vs metrics, `\spancite` vs `full`, bib-coverage, results-table-fresh, claims-have-evidence, exp-have-hypotheses. LLM rubric rows exist as data for an *agentic* layer, not as engine judges |
| `lint.run` via MCP `check_invariants` / cockpit | Unbacked headlines, none-verdict support, toy-only, contradictions, done-exp-without-run, dangling questions, exploratory-only, stale evidence, untested hypotheses, dangling context links, phase order. CLI **PR #28** |
| `finding accept\|reject` | Rejected fingerprints never re-nag |
| `refs scan\|check\|where` | `@renv` code tags resolve to store entities |
| PR #28 adds | `--strict`; non-waivable findings; tabular-cell number matching; `\input` sidecars; `bib-known-paper` |

### Intentionally not implemented (and should stay that way)

- An LLM that writes `text/*.tex` as a product feature
- LLM-as-judge of whether a number is “close enough”
- `ideas.md` / `program.md` / `answer.md` / Neo4j world model
- Consensus / citation-count as claim support
- Executing model-authored code inside `renv/research/`
- Wet-lab drivers
- `renv publish` / renv.ai companion graph — **planned**, not live (see README)

---

## Steal vs refuse (short list)

Fits the invariants — implement as store writes, lints, or review checks:

1. **Never strip `\spancite`.** ScientistOne’s Compose step is the bug; renv already does the right thing.
2. **`renv exp recheck`** — I1 as a run: re-execute the pinned artifact, write metrics, compare to the woven table.
3. **Bind manuscript numbers to a `run_id`** — closes ASv2 cherry-pick.
4. **Bib existence** — PR #28 locally; optional Crossref/S2 extra later. Never “skip the API if rate-limited and trust the model.”
5. **Retraction / expression-of-concern** column on `paper`.
6. **Method–code alignment** as AST/regex lint findings, not LLM I4.
7. **Curie partitions** as a cockpit *view* of the experiment DAG.
8. **STORM-style questions** as `log` entries of type `question` (already the type).
9. **Virtual Lab human gates** as `feedback` (`--source`) and `decision` entries, logged *before* the pivot.
10. **PaperQA / PaSa / OpenScholar** as ingest/query helpers; every answer still needs `cite --write`.
11. **PROV-O / JSON export** — `renv export` is the snapshot; a typed provenance extra is compatible.
12. **OA PDF attach** extra — DOI rows currently have metadata and no text, so span cite cannot land until `renv add <pdf> --key`.

Refuse even if the stars are large:

- LLM writer, LLM reviewer, LLM integrity majority vote
- Second markdown/YAML/graph store
- Generating papers as the measure of success
- Executing untrusted agent code in the engine
- Treating retrieval confidence, citation counts, or “the literature agrees” as `claim` status
- Skill packs / prompt marketplaces as a replacement for `AGENTS.md`

---

## Honest gaps (renv, this snapshot)

Relative to the landscape, not to a wish list:

| Gap | Who has a version of it | Why it matters |
|---|---|---|
| No re-execution of the claimed score | ScientistOne I1, Curie | Weave proves the *table* matches the *store*, not that the store matches the world |
| No manuscript ↔ single `run_id` | (nobody, which is why ASv2 cherry-picks) | Highest-leverage anti-fraud check we do not yet do |
| No method–code lint | ScientistOne I4 (LLM) | In-scope if deterministic |
| `declare_test` / paper annotate / `renv lint` thin on CLI | InternAgent files; cockpit already has notes | Agent-loop friction; PRs #28 and #30 |
| Two search surfaces | PaperQA is one | Store FTS (`search`) ≠ corpus index (`cite` / `search_corpus`) |
| Default verifier is lexical overlap | FactCG is `--extra verify-local` | Faithful paraphrase scores `none` (correct for a copy-detector, surprising for a scientist) |
| `renv add` does not put papers in the human inbox | `references add` does | Inbox is the human’s job; cold ingest skips it |
| No retraction metadata | Scite / publishers | A span cite to a retracted paper currently looks like any other cite |
| Plaintext `.txt` papers in the cockpit | — | PDF viewer is first-class; demo `.txt` sources do not open the same way |
| No live Crossref/S2 on the write path | ScientistOne I3, ARC | Ghost citations (GhostCite; NeurIPS 2025 fabricated cites) are an industry failure mode we only partially block: you cannot span-cite text that is not in `library/`, but you *can* still put a hallucinated key in a raw `\cite` |

---

## Further reading

Curated surveys (not scientists):
[ResearAI/Awesome-AI-Scientist](https://github.com/ResearAI/Awesome-AI-Scientist),
[openags/Awesome-AI-Scientist-Papers](https://github.com/openags/Awesome-AI-Scientist-Papers),
[tsinghua-fib-lab/Awesome-AI-Scientists](https://github.com/tsinghua-fib-lab/Awesome-AI-Scientists).

Failure-mode papers worth keeping in the corpus when this landscape is cited
from a project: ALCE (Gao et al. 2023), the telephone-game citation paper,
ScientistOne (Meng et al. 2026), the AI Scientist independent eval
(arXiv:2502.14297), GhostCite (arXiv:2602.06718). Ingest them with `renv add`
and span-cite; do not treat this markdown as evidence.
