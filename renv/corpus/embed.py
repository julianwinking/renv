"""Embedders behind one interface.

Default is a pure-stdlib lexical TF-IDF embedder so the whole pipeline runs today
on Python 3.14 with no torch. The SOTA backends (Qwen3-Embedding / BGE-M3 via
sentence-transformers, or Voyage/OpenAI APIs) are drop-in replacements selected
through the lockfile — swap the config, re-index, and citations still resolve
because anchors carry the quoted text, not vector ids.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> list[str]:
    return _WORD.findall(s.lower())


class Embedder(Protocol):
    name: str
    model: str

    def fit(self, corpus: list[str]) -> None: ...
    def encode(self, texts: list[str]) -> list[dict]: ...  # sparse or dense vectors
    def is_sparse(self) -> bool: ...


class LexicalEmbedder:
    """TF-IDF sparse vectors with cosine similarity. Deterministic, no deps."""

    name = "lexical"

    def __init__(self, model: str = "tfidf-builtin"):
        self.model = model
        self.idf: dict[str, float] = {}
        self._n = 0

    def is_sparse(self) -> bool:
        return True

    def fit(self, corpus: list[str]) -> None:
        self._n = len(corpus)
        df: Counter = Counter()
        for doc in corpus:
            for tok in set(_tokens(doc)):
                df[tok] += 1
        self.idf = {t: math.log((1 + self._n) / (1 + c)) + 1.0 for t, c in df.items()}

    def _vec(self, text: str) -> dict:
        tf = Counter(_tokens(text))
        if not tf:
            return {}
        vec = {t: (c / sum(tf.values())) * self.idf.get(t, math.log(1 + self._n) + 1.0)
               for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def encode(self, texts: list[str]) -> list[dict]:
        return [self._vec(t) for t in texts]


class SentenceTransformerEmbedder:
    """Dense embeddings via sentence-transformers (Qwen3-Embedding, BGE-M3, ...)."""

    name = "sentence-transformers"

    def __init__(self, model: str = "Qwen/Qwen3-Embedding-0.6B"):
        self.model = model
        self._st = None

    def is_sparse(self) -> bool:
        return False

    def _load(self):
        if self._st is None:
            from sentence_transformers import SentenceTransformer  # lazy
            self._st = SentenceTransformer(self.model)
        return self._st

    def fit(self, corpus: list[str]) -> None:  # no global fit needed
        return None

    def encode(self, texts: list[str]) -> list[dict]:
        vecs = self._load().encode(texts, normalize_embeddings=True)
        return [{"__dense__": list(map(float, v))} for v in vecs]


def cosine(a: dict, b: dict) -> float:
    if "__dense__" in a and "__dense__" in b:
        va, vb = a["__dense__"], b["__dense__"]
        return float(sum(x * y for x, y in zip(va, vb)))  # both pre-normalized
    # sparse dot product (vectors are unit-normalized)
    if len(a) > len(b):
        a, b = b, a
    return float(sum(v * b.get(t, 0.0) for t, v in a.items()))


def get_embedder(name: str, model: str) -> Embedder:
    if name == "lexical":
        return LexicalEmbedder(model)
    if name == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    raise ValueError(f"unknown embedder backend {name!r}")
