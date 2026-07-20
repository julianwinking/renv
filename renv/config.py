"""The lockfile.

The whole point: store *how* the library was indexed so anyone handed this config
+ the same PDFs reproduces an identical index, and so a citation's anchor can be
re-resolved deterministically. Think package-lock.json for a paper corpus.

The lockfile pins the moving parts (parser, chunker, embedder + versions) and a
content hash per source file. The citation anchor itself does NOT depend on this
config (it embeds the quoted text — see selectors.py); the lockfile only
guarantees that *retrieval* and *re-anchoring* are reproducible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

CONFIG_FILENAME = "renv.lock.json"


@dataclass
class Config:
    # --- parser ---
    parser: str = "plaintext"          # plaintext | pdfminer | docling
    parser_version: str = "builtin"

    # --- chunker ---
    chunker: str = "sentence"          # sentence | paragraph
    chunk_min_chars: int = 40          # drop tiny fragments
    chunk_max_chars: int = 1200        # split overly long passages

    # --- anchor context ---
    anchor_context_chars: int = 32     # prefix/suffix length for TextQuoteSelector

    # --- embedder ---
    embedder: str = "lexical"          # lexical | sentence-transformers | openai | voyage
    embedder_model: str = "tfidf-builtin"
    embedder_version: str = "builtin"
    embedder_dims: int | None = None

    # --- retrieval ---
    top_k: int = 5

    def fingerprint(self) -> str:
        """Stable hash of the index-determining settings (excludes top_k)."""
        keys = [
            "parser", "parser_version", "chunker", "chunk_min_chars",
            "chunk_max_chars", "anchor_context_chars", "embedder",
            "embedder_model", "embedder_version",
        ]
        blob = json.dumps({k: getattr(self, k) for k in keys}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class SourceRecord:
    """One indexed file in the corpus manifest."""
    source_id: str          # stable id used in citations (filename stem by default)
    path: str               # relative path under the library root
    sha256: str             # content hash of the raw bytes
    n_chunks: int = 0
    title: str | None = None


@dataclass
class Lockfile:
    config: Config = field(default_factory=Config)
    sources: list[SourceRecord] = field(default_factory=list)
    config_fingerprint: str = ""

    def save(self, root: Path) -> Path:
        self.config_fingerprint = self.config.fingerprint()
        out = Path(root) / CONFIG_FILENAME
        payload = {
            "config": self.config.to_dict(),
            "config_fingerprint": self.config_fingerprint,
            "sources": [asdict(s) for s in self.sources],
        }
        out.write_text(json.dumps(payload, indent=2))
        return out

    @classmethod
    def load(cls, root: Path) -> "Lockfile":
        p = Path(root) / CONFIG_FILENAME
        data = json.loads(p.read_text())
        return cls(
            config=Config.from_dict(data["config"]),
            sources=[SourceRecord(**s) for s in data.get("sources", [])],
            config_fingerprint=data.get("config_fingerprint", ""),
        )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()
