"""Two abstractions: a shared Corpus, and per-paper Projects that cite it.

The engine (this package) lives at the repo root alongside a single shared
**corpus** of every paper you have read. Many **projects** (papers you are
writing) retrieve against that one corpus.

    recursive-referencing/        repo root = engine + shared corpus
        renv/  tests/            the engine
        library/                  SHARED references (all papers read)   INPUT
        .renv/                   SHARED index + lockfile               DERIVED
        projects/
            <paper>/
                src/              the paper's code
                text/             the LaTeX being authored
                citations.json    anchored cites for this paper         OUTPUT

Projects store no PDFs. A citation pins its source by content hash + quoted span
(see selectors.py), so a finished paper's citations keep resolving even as the
shared library grows or its files are re-versioned.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Corpus:
    """The shared, indexed reference library."""
    root: Path = Path(".")

    def __post_init__(self):
        self.root = Path(self.root)

    @property
    def library(self) -> Path:
        return self.root / "library"

    @property
    def artifacts(self) -> Path:
        return self.root / ".renv"

    def ensure_artifacts(self) -> Path:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        return self.artifacts

    def is_indexed(self) -> bool:
        from .config import CONFIG_FILENAME
        from .store import INDEX_FILENAME
        return (self.artifacts / CONFIG_FILENAME).exists() and \
               (self.artifacts / INDEX_FILENAME).exists()

    def validate(self) -> None:
        if not self.library.exists():
            raise FileNotFoundError(
                f"no shared library at {self.library} — put reference papers there"
            )


@dataclass
class Project:
    """One paper's workspace. Retrieves against a Corpus; holds no references."""
    root: Path

    def __post_init__(self):
        self.root = Path(self.root)

    @property
    def src(self) -> Path:
        return self.root / "src"

    @property
    def text(self) -> Path:
        return self.root / "text"

    @property
    def citations_path(self) -> Path:
        return self.root / "citations.json"

    def ensure(self) -> None:
        self.src.mkdir(parents=True, exist_ok=True)
        self.text.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if not self.root.exists():
            raise FileNotFoundError(f"project not found: {self.root}")
