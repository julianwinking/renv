"""Does the cited span actually support the claim?

This is the step that makes the system more than RAG: it implements ALCE-style
citation precision (flag a span that does not entail the claim). Default backend
is a transparent lexical-overlap heuristic that runs with no deps; the SOTA
upgrade is FactCG-DeBERTa-v3 (MIT, NAACL 2025) or an LLM judge.

Verdict mirrors the literature's three-level support taxonomy
(full / partial / no support; Zhang et al., INLG 2024).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("the a an of to in and or for is are was were be been on with that this "
            "as by at from it its their our we they he she which not no than then".split())


def _content(s: str) -> Counter:
    return Counter(t for t in _WORD.findall(s.lower()) if t not in _STOP and len(t) > 2)


@dataclass
class Verdict:
    support: str          # "full" | "partial" | "none"
    score: float          # 0..1
    backend: str
    rationale: str = ""


class Verifier(Protocol):
    def check(self, claim: str, evidence: str) -> Verdict: ...


class LexicalOverlapVerifier:
    """Content-word recall of the claim within the evidence span.

    Cheap and explainable, not a real entailment model — a placeholder that keeps
    the pipeline honest about *what it can and cannot* assert. Use FactCG/LLM for
    anything load-bearing.
    """

    def __init__(self, full: float = 0.6, partial: float = 0.3):
        self.full, self.partial = full, partial

    def check(self, claim: str, evidence: str) -> Verdict:
        c, e = _content(claim), _content(evidence)
        if not c:
            return Verdict("none", 0.0, "lexical", "empty claim")
        covered = sum(1 for t in c if t in e)
        score = covered / len(c)
        support = "full" if score >= self.full else "partial" if score >= self.partial else "none"
        missing = [t for t in c if t not in e][:6]
        return Verdict(support, round(score, 3), "lexical",
                       f"covered {covered}/{len(c)} content words; missing: {missing}")


class FactCGVerifier:
    """SOTA permissive grounding check: yaxili96/FactCG-DeBERTa-v3-Large (MIT)."""

    def __init__(self, model: str = "yaxili96/FactCG-DeBERTa-v3-Large"):
        self.model = model
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            from transformers import pipeline  # lazy
            self._pipe = pipeline("text-classification", model=self.model)
        return self._pipe

    def check(self, claim: str, evidence: str) -> Verdict:
        out = self._load()(f"{evidence} [SEP] {claim}")[0]
        label = str(out["label"]).lower()
        score = float(out["score"])
        supported = ("support" in label) or label in {"1", "label_1", "entailment"}
        if supported:
            return Verdict("full" if score >= 0.5 else "partial", score, "factcg", label)
        return Verdict("none", score, "factcg", label)


def get_verifier(name: str) -> Verifier:
    if name == "lexical":
        return LexicalOverlapVerifier()
    if name == "factcg":
        return FactCGVerifier()
    raise ValueError(f"unknown verifier {name!r}")
