"""Build, persist, and load the index.

The index is a JSON sidecar living next to the lockfile under the library root.
Each record carries the chunk text, its char offsets, page, the W3C anchor, and
the embedding vector. Plain JSON keeps the MVP inspectable and dependency-free;
swap to LanceDB/FAISS when the corpus outgrows it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from .selectors import Anchor

INDEX_FILENAME = "reref.index.json"


@dataclass
class IndexRecord:
    source_id: str
    chunk_id: int
    text: str
    start: int
    end: int
    page: int | None
    anchor: dict          # Anchor.to_dict()
    vector: dict          # sparse {token: w} or {"__dense__": [...]}


@dataclass
class Index:
    config_fingerprint: str
    records: list[IndexRecord]

    def save(self, root: Path) -> Path:
        out = Path(root) / INDEX_FILENAME
        payload = {
            "config_fingerprint": self.config_fingerprint,
            "records": [asdict(r) for r in self.records],
        }
        out.write_text(json.dumps(payload))
        return out

    @classmethod
    def load(cls, root: Path) -> "Index":
        data = json.loads((Path(root) / INDEX_FILENAME).read_text())
        return cls(
            config_fingerprint=data["config_fingerprint"],
            records=[IndexRecord(**r) for r in data["records"]],
        )

    def anchor_for(self, rec: IndexRecord) -> Anchor:
        return Anchor.from_dict(rec.anchor)
