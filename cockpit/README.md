# renv cockpit

The all-in-one research UI over the `renv` store — the place to *drive* a
project, not just look at it. It talks to the Python backend's JSON API
(`renv web`); every write goes through the same domain functions as the CLI
and the MCP server, so the store stays the single source of truth and agents
and humans always see identical live state.

## What's inside

- **Overview** — project health, open questions, and what moved recently.
- **Papers** — the corpus library plus a tabbed PDF reader: positional
  annotations, span-anchored citations highlighted in place, reference
  intelligence (traffic-light `[N]` markers, hover cards, add / not-relevant
  verdicts), a reading inbox, and side-by-side note documents.
- **Claims** — the claim/evidence graph with derived status, grades,
  retractions, and pre-registered tests.
- **Experiments** — the branch DAG with runs and metrics.
- **Findings** — review findings with inline accept / reject (reasoning
  required; rejected findings are never re-raised).
- **Graph** — everything above as one interactive canvas (React Flow +
  dagre): experiments, claims, findings, citations, papers, and notes as
  connected, expandable nodes, with regions and phase bands.
- **Timeline, Log, Plan** — the decision log and the Gantt view of phases.

## Run it

The built cockpit is served by the backend — from the repo root:

```bash
uv run renv web            # http://127.0.0.1:8765
uv run renv web install    # https://renv.local — on-demand site; also builds
                           # this bundle if it is missing (macOS, one command)
```

If no build exists yet, `renv web` serves a page with the build instructions.

## Develop

Two processes, hot reload on edits:

```bash
uv run renv web                              # backend JSON API at :8765
cd cockpit && npm install && npm run dev     # Vite at :5173 (proxies /api)
```

## Build by hand

```bash
cd cockpit && npm install && npm run build   # → cockpit/dist, picked up by renv web
```
