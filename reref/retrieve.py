"""Retrieve candidate source spans for a claim and verify support."""

from __future__ import annotations

from dataclasses import dataclass

from .embed import Embedder, cosine
from .store import Index, IndexRecord
from .verify import Verdict, Verifier


@dataclass
class Candidate:
    record: IndexRecord
    similarity: float
    verdict: Verdict | None = None


class Retriever:
    def __init__(self, index: Index, embedder: Embedder, verifier: Verifier | None = None):
        self.index = index
        self.embedder = embedder
        self.verifier = verifier

    def search(self, claim: str, top_k: int = 5, verify: bool = True) -> list[Candidate]:
        qvec = self.embedder.encode([claim])[0]
        scored = [
            Candidate(rec, cosine(qvec, rec.vector))
            for rec in self.index.records
        ]
        scored.sort(key=lambda c: c.similarity, reverse=True)
        top = scored[:top_k]
        if verify and self.verifier is not None:
            for c in top:
                c.verdict = self.verifier.check(claim, c.record.text)
            # prefer supported spans, then similarity
            rank = {"full": 2, "partial": 1, "none": 0}
            top.sort(key=lambda c: (rank.get(c.verdict.support, 0) if c.verdict else 0,
                                    c.similarity), reverse=True)
        return top
