# How a thesis argument is built

A thesis (the document or the claim) is one falsifiable statement plus a
chain of supported lemmas. In this environment the chain is literal: the
thesis is a claim (kind=thesis), lemmas are claims it `depends_on`, and each
must be `supported` by runs or citations before the writing asserts it.

## The spine
1. **One sentence thesis.** If it needs "and", it is two theses — split it.
2. **Decompose into lemmas** the reader can verify independently. Each lemma
   is a claim node; the thesis `depends_on` them. A lemma nobody could refute
   is not a lemma, it is background.
3. **For each lemma: evidence plan before evidence.** Which experiment or
   citation would support it — and, more important, what result would REFUTE
   it. Design the refuting experiment first; it is usually cheaper.
4. **Calibrate the instrument before trusting it.** First experiments verify
   the harness against known/closed-form behavior; only then do results carry
   evidential weight.

## Defending it
- Anticipate the strongest objection per chapter and answer it in-text
  (advisor feedback entries are the rehearsal for this).
- Distinguish three strengths of statement and never blur them:
  *demonstrated* (supported claim), *suggested* (partial evidence),
  *conjectured* (open claim). The word chosen must match the claim status.
- A chapter's conclusion may only restate claims whose status is `supported`.

## Chapter order (default)
Introduction (thesis + roadmap) → Background (only what the lemmas need) →
one chapter per lemma-cluster (method + evidence together) → Synthesis
(the thesis re-argued from proved lemmas) → Limitations & future questions
(the open claims and questions, honestly labeled).
