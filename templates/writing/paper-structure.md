# How a research paper is built

Instructions for anyone (human or agent) drafting `text/paper.tex`. Every
number comes from `reref weave`; every literature claim from a verified
`\spancite`. This file says what each section must *accomplish* — not decorate.

## Abstract (4–6 sentences, one job each)
1. Context: the problem domain in one sentence a non-specialist follows.
2. Gap: what existing work cannot do (this sentence justifies the paper).
3. Approach: the mechanism, named concretely.
4. Result: the headline number(s) — from a `metric` row, never typed.
5. Implication: what changes if the reader believes you.

## Introduction
- First paragraph earns the topic; last paragraph enumerates contributions.
- Contributions are the paper's claims (kind=contribution in the store) —
  numbered, falsifiable, each later matched by evidence in Results.
- No related-work survey here; one or two positioning sentences at most.

## Related work
- Organize by *idea*, not by paper. Each cited work gets a delta sentence:
  what it does AND how we differ. A citation without a delta is filler.
- Every factual statement about a paper must be a verified span citation.

## Method
- State assumptions before mechanisms. Define notation once, use it forever.
- A reader should be able to re-implement from this section alone; anything
  needed for reproduction that doesn't fit goes to an appendix, not omitted.

## Experiments
- Open with the questions being answered (they mirror experiment hypotheses
  in the store — one experiment, one question).
- Setup: datasets (registered + hashed), baselines, metrics (defined in the
  metric registry), seeds/variance policy.
- Results tables are woven (`reref weave`) — never hand-edited.

## Results / Analysis
- Lead each paragraph with the finding, then the evidence, then the caveat.
- Negative and null results that shaped the design belong here, briefly.

## Conclusion
- Restate the thesis as *demonstrated* (only if its claim is `supported`),
  the honest limitations, and one concrete next question.
