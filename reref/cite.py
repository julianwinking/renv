"""Render an anchored citation: a LaTeX macro + a machine-readable sidecar.

LaTeX has no native span anchor, so we emit a self-contained \\spancite that
carries the source id, the position hint, and the quoted text. The quote makes
the citation self-verifying; the sidecar (citations.json) stores the full W3C
anchor + verdict for tooling and re-resolution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from .retrieve import Candidate

# Drop this in your preamble; it prints [id:start-end] and footnotes the quote.
LATEX_PREAMBLE = r"""
% recursive-referencing span citation
\newcommand{\spancite}[4]{%
  % #1 source id, #2 start, #3 end, #4 quoted span
  \textsuperscript{[\,#1:#2--#3\,]}\footnote{#1, chars #2--#3: ``#4''}%
}
"""


@dataclass
class Citation:
    claim: str
    source_id: str
    source_sha256: str        # pins the exact source version cited
    start: int
    end: int
    page: int | None
    quote: str
    prefix: str
    suffix: str
    support: str
    support_score: float
    similarity: float

    def latex(self) -> str:
        q = self.quote.replace("\\", "\\textbackslash{}").replace("&", "\\&")
        return f"\\spancite{{{self.source_id}}}{{{self.start}}}{{{self.end}}}{{{q}}}"

    def to_dict(self) -> dict:
        return asdict(self)


def make_citation(claim: str, cand: Candidate, source_sha256: str = "") -> Citation:
    rec = cand.record
    a = rec.anchor["quote"]
    v = cand.verdict
    return Citation(
        claim=claim,
        source_id=rec.source_id,
        source_sha256=source_sha256,
        start=rec.start,
        end=rec.end,
        page=rec.page,
        quote=a["exact"],
        prefix=a.get("prefix", ""),
        suffix=a.get("suffix", ""),
        support=v.support if v else "unverified",
        support_score=v.score if v else 0.0,
        similarity=round(cand.similarity, 4),
    )


def append_sidecar(root: Path, citation: Citation, filename: str = "citations.json") -> Path:
    p = Path(root) / filename
    data = json.loads(p.read_text()) if p.exists() else []
    data.append(citation.to_dict())
    p.write_text(json.dumps(data, indent=2))
    return p
