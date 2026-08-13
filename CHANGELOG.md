# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/); versions tag `vX.Y.Z`.

## [Unreleased]

- `renv lint <project>`: CLI for the graph-lint catalog (MCP `check_invariants`
  with a project already had it). `renv review --strict` runs lints then review
  and fails on open HIGH from either.
- Non-waivable findings: unverified `\spancite`, a stale `results_table.tex`,
  unknown cite keys, §0 result-without-run, and none-verdict "support" cannot
  be rejected; a prior reject is reopened rather than duplicated. Coincidence
  unmatched numbers stay waivable.
- Prose numbers must match a `results_table.tex` cell, not merely a metric in
  the DB (so skipping `renv weave` no longer lets an abstract number pass).
- `bib-known-paper`: every `\cite` / `\spancite` key must exist as a paper row
  (HIGH, non-waivable). `bib-coverage` still flags keys missing from the bib.
- Graph lints (medium, waivable): cited paper with no PDF text; typed remote
  ingest with no entrypoint; evidential run is not the experiment's latest
  (weave still emits latest).
- Weave writes `% runs: slug=id` next to the generated banner.
- Property-based tests (hypothesis) for the reference-list and BibTeX parsers.
- Architecture decisions #10 (clients split on touch) and #11 (no typing
  retrofit) recorded in AGENTS.md.

## [0.1.0] — 2026-07-21

First coherent cut of the engine + cockpit.

- Corpus pipeline: parse → chunk → embed → index → span-anchored, verified
  citations (`renv cite`), lexical defaults with SOTA extras.
- Research store: claims/evidence with derived status, experiment DAG with
  reproducible runs, typed decision log, findings review, plan; deterministic
  JSONL export (now covering every non-presentation table).
- Papers: arXiv/DOI/PDF/BibTeX ingest, reference intelligence in the PDF
  viewer (traffic-light markers, hover cards, verdicts), reading inbox.
- Clients: CLI, stdio MCP server, web cockpit (React) — one store, thin
  clients, layering enforced by an architecture test.
- Tooling: ruff + coverage ratchet in CI on Python 3.10/3.14, cross-agent
  instruction files (AGENTS.md canonical; Claude/Codex/Cursor adapters).
