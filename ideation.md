# Ideation

This file holds two related but distinct ideas:
1. **Fine-grained, location-anchored citation**
2. **Reasoning lines** (a separate idea, parked at the bottom).

---

# Paper: Fine-grained, location-anchored citation

## Problem
More researchers are using large language models (LLMs) to help with their work. A major limitation is hallucination, which shows up in two distinct ways for citations:

1. **Fabricated references** — the cited paper does not exist. This is largely addressable today by checking reference names/links against an index (Google Scholar, DOI lookup), and can be moved into the LaTeX source by referencing a publication link directly.
2. **Unsupported / distorted attribution** — the reference exists, but it does not actually support the claim attributed to it. This is the harder, still-unsolved problem and the one this paper targets.

The root cause of (2) is that an LLM may cite a paper without reading it, or after reading only the abstract. (This is a documented failure mode — to confirm against the citation-faithfulness / attributed-QA literature.) Tools like Anara already index a PDF into chunks and reference exact chunks on retrieval, which points at the mechanism we want to build on. This could become a component of autoresearch pipelines.

## Core idea
Today, in technical fields, a citation points only at a whole paper, attached at the end of a sentence. The proposal is to make citations **location-anchored**: each citation points to the *exact place* in the source it draws from — not just the paper, but the specific span (sentence, line, or indexed chunk/vector).

This assumes papers can be indexed in a standardized way. Anara does this in the cloud; a **local vector index over a researcher's personal paper storage** is enough to demonstrate the approach (and is the MVP).

A key open problem to address: **anchors must be stable.** Line numbers break across versions, preprint vs. typeset, and two-column layouts; chunk vectors are tool-specific and non-portable. A standard needs robust anchoring (e.g. quote/semantic-span based) rather than raw line numbers. Or the paper author would run this together with their publication process so that everybody has the same line numbers long-term.

## Contributions (one paper)
1. **Location-anchored citation** — the mechanism above, with a stable anchoring scheme and a local indexing implementation.
2. **Hallucination & correctness checking** — because each citation resolves to a specific source span, we can automatically check whether the cited span actually supports the claim. This detects unsupported/distorted attributions, not just fabricated references. *(builds on contribution 1)*
3. **Cross-paper reasoning chains + visualization** — when papers build on each other, location-anchored citations let us reconstruct and visualize how reasoning is layered across papers and how references connect. *(builds on contributions 1 & 2)*
4. **Application to peer review** — a standardized, location-anchored format makes it transparent where a paper's claims come from and what its actual novel additions are, which could be applied as a reviewing aid.

## Positioning (must do before writing)
Position explicitly against prior art — this is the make-or-break for novelty:
- Attributed QA / citation generation & evaluation (e.g. ALCE-style citation metrics).
- Citation faithfulness / unsupported-attribution detection.
- Scientific claim verification (e.g. SciFact).
- Commercial tools: Anara, SciSpace, Elicit, Consensus, scite.ai.

The novelty claim must be made *against* this body of work.

## Evaluation (design this first, then build only what it needs)
Construction alone is a demo, not a paper. Needed:
- **Dataset** with ground truth: claims labeled supported / unsupported / fabricated.
- **Baselines** to beat: paper-level citation + plain LLM, and existing RAG-attribution tools.
- **Metrics**: citation precision/recall, attribution faithfulness, hallucination-detection rate.
- Writing my own paper with this method is a useful demo, but **N=1 on my own paper is not evidence** — it invites a self-fulfilling-prophecy critique. The visualization is a figure, not a result.

## Thesis (one testable claim)
> Fine-grained, location-anchored citations enable automatic detection of unsupported/distorted attributions in scientific writing better than paper-level citation plus existing RAG.

---

# Separate idea: Reasoning lines

There is a lot between the lines of a paper that a researcher knows during writing but never writes down. The idea: interleave an explicit **reasoning line** between a paper's sentences (at section, paragraph, and sentence granularity) to make this implicit knowledge explicit — improving transparency, easier correctness-checking, and preventing AI iterations from losing the context that lives in notes rather than the final text.

**Open problems to resolve before this is its own paper:**
- **Provenance & trust.** If a human writes the reasoning lines, this is a tooling/workflow contribution and adoption is the central challenge. If an LLM generates them, the reasoning lines are themselves potentially hallucinated — you've added a layer that needs verifying, not one that reduces verification.
- **Circularity.** Using an LLM to make reasoning explicit and then an LLM to check correctness can launder confidence rather than establish it; the evaluation must not just measure self-consistency.
