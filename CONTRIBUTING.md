# Contributing to renv

Thanks for your interest in improving renv. This document covers the practical
workflow. The design rules that PRs are reviewed against live in
[`AGENTS.md`](AGENTS.md); reading it first will save you review cycles.

## Development setup

The project is managed with [uv](https://docs.astral.sh/uv/). The core runs on
the Python stdlib only, so setup is fast:

```bash
git clone https://github.com/julianwinking/renv && cd renv
uv sync                 # creates .venv, installs dev tooling (pytest)
uv run pytest           # the whole suite should pass before you start
```

For the React cockpit:

```bash
cd cockpit
npm install
npm run dev             # Vite dev server at :5173, proxies /api to `renv web`
npm run build           # production bundle served by `renv web`
```

## Making changes

1. Branch from `main`.
2. Keep the architecture invariants intact. The ones that most often bite:
   - **One store, thin clients.** The SQLite DB is the single ground truth.
     Never write to it with raw SQL from a client and never re-implement a
     domain rule inside the CLI, the MCP server, or the cockpit. Add or extend
     a domain function and expose it through all three.
   - **Provenance is enforced.** Measured numbers enter only via recorded
     runs; claim and question status is derived from evidence, never set.
   - **stdlib-first.** The default install must not require compilation or
     heavy packages. New heavy backends go behind an optional extra and a lazy
     import.
3. Add or extend tests in `tests/`. The suite is dependency-free on purpose;
   keep it that way.
4. Run `uv run pytest` and, if you touched the cockpit, `npm run build`.
5. Open a PR using the template. CI runs the test suite on the oldest and
   newest supported Python plus a cockpit build; all checks must pass.

## Coding agents (Claude Code, Codex, Cursor, …)

`AGENTS.md` is the single canonical instruction file — every agent-specific
entry point defers to it rather than duplicating it:

Skills use the cross-vendor `SKILL.md` shape (one folder per skill in the
neutral `skills/` directory); each agent folder holds only a symlink:

- **Codex**: reads root `AGENTS.md` natively; `.codex/skills/<name>` →
  `skills/<name>`; `.codex/config.toml` registers the renv MCP server.
- **Claude Code**: `CLAUDE.md` → `AGENTS.md`; `.claude/skills/<name>` →
  `skills/<name>`; `.mcp.json` registers the MCP server.
- **Cursor**: `.cursor/rules/protocol.mdc` points at `AGENTS.md`;
  `.cursor/commands/<name>.md` → `skills/<name>/SKILL.md`;
  `.cursor/mcp.json` → `.mcp.json`.

Add new agent guidance to `AGENTS.md` only. New skill: create
`skills/<name>/SKILL.md`, then add the three symlinks above.

## Commit style

Short imperative subject lines, optionally prefixed by the area you touched
(`cite:`, `cockpit:`, `store:`). Explain the why in the body when it is not
obvious.

## Reporting bugs and proposing features

Please use the issue templates. For security problems, report privately via
[GitHub security advisories](https://github.com/julianwinking/renv/security/advisories/new)
instead of opening a public issue.
