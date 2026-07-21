# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/); versions tag `vX.Y.Z`.

## [Unreleased]

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
