<!-- What does this PR do? Link the issue it closes, if any. -->

---

- [ ] `uv run pytest` passes and new behavior is covered by a test
- [ ] The core still runs on the Python stdlib only (heavy deps stay behind optional extras)
- [ ] CLI, MCP, and cockpit stay thin clients over the same domain functions (no raw SQL writes, no client-side rules)
