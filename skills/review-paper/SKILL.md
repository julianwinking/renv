---
name: review-paper
description: Per-section agentic paper review — automated checks + adversarially-verified LLM checks. Invoke with a project slug.
---

Review the paper for the given project slug in fine-grained, per-section detail. Do NOT do
one big sweep — work the rubric check by check.

## 1. Automated checks (ground truth — run first)
Run `uv run renv review <project-slug>`. These are deterministic facts cross-checked against
the store (abstract numbers vs. metric rows, `\spancite` vs. verified citations,
bib coverage, results-table freshness, experiment hypotheses). Treat every HIGH
finding as a blocker. Read the saved report path it prints.

## 2. LLM checks (the rubric's `verify: llm` rows)
Fetch the rubric: call the `rubric` MCP tool (or read `renv/review.py:RUBRIC`).
For each `llm` check, and for each major section of `projects/<project-slug>/text/paper.tex`:

- **Find** concrete, located issues for that (section × dimension) — quote the
  exact sentence, give a one-line fix. Be specific; "tighten the intro" is useless.
- **Adversarially verify** each finding before reporting it: try to refute it
  (is the claim actually supported elsewhere? is the positioning in fact stated?).
  Drop findings you cannot defend. Prefer 5 real issues over 30 nitpicks.

Use the MCP tools to ground every claim: `get_card <key>` for what a cited paper
actually says, `paper_usage <key>` for where it is used, `query` for store facts.
Never assert a problem about a citation without checking the source span.

## 3. Synthesize
Append your verified findings to the report file from step 1, grouped by section,
each as: `- [SEVERITY] (dimension): issue [exact location] → fix`. End with the
3 highest-leverage fixes. If `renv review` had HIGH findings, state that the
paper is not release-ready until they are resolved.
