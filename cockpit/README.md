# renv cockpit (React Flow graph UI)

An interactive graph view over the `renv` research store — experiment branches
(DAG), claims, findings, citations, and papers as connected, expandable nodes.
Talks to the Python backend's JSON API (`renv web`). The store stays the single
source of truth; this is just a richer frontend.

## Develop
Two processes:
```bash
renv web                    # backend JSON API at http://127.0.0.1:8765
cd cockpit && npm install && npm run dev    # Vite dev server at http://127.0.0.1:5173 (proxies /api)
```
Open http://127.0.0.1:5173 — hot reload on edits.

## Build (served by `renv web`)
```bash
cd cockpit && npm install && npm run build   # → cockpit/dist
renv web                                     # serves the built app at http://127.0.0.1:8765
```
`renv web` serves `cockpit/dist/` if present, else falls back to the lightweight
buildless page in `renv/web/`.

## What's in the graph
- **Experiment** nodes (status + metrics; click to expand the hypothesis), wired
  parent→child into the branch DAG.
- **Claim** nodes with derived status; edges to their supporting/refuting evidence.
- **Finding** nodes with inline **accept / reject** (reasoning required; rejected
  findings are never re-raised).
- **Citation** + **Paper** nodes (citation → paper provenance).

Layout is dagre (left→right). All writes go through the same domain functions as
the CLI and the MCP server.
