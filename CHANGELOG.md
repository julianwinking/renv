# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/); versions tag `vX.Y.Z`.

## [Unreleased]

- Cockpit **Write** view: Overleaf-shaped `text/` editor (file tree + LaTeX +
  PDF preview). Citations insert `\\spancite` via the same retrieve/verify path
  as `renv cite`; results tables stay woven from metric rows. Compile uses a
  local TeX engine when present (latexmk, tectonic, or pdflatex) — WASM TeX is
  not bundled (lean core). New CLI `renv compile` and MCP `compile_manuscript`.
  Pane chrome is a shared 40px bar (same as Papers tabs) so `text/`, the
  filename, and PDF sit on one baseline; the file tree is not a nav `<aside>`
  (that padding was dropping the `text/` title off the filename). Weave/Recompile
  live on the PDF pane.
- web.py API routing is a dispatch table (AGENTS.md #10).
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
