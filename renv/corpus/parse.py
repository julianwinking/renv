"""Parse a source document to plain text + per-page offsets.

Default backend is stdlib (.txt / .md). PDFs use pdfminer.six (a core
dependency); Docling (MIT, page_no + bbox + charspan) is the documented upgrade for
precise layout-aware offsets. All backends return text whose character indices
are the coordinate system every downstream offset (chunks, selectors) refers to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageSpan:
    page: int
    start: int
    end: int


@dataclass
class ParsedDoc:
    source_id: str
    text: str
    backend: str
    pages: list[PageSpan] = field(default_factory=list)

    def page_of(self, offset: int) -> int | None:
        for ps in self.pages:
            if ps.start <= offset < ps.end:
                return ps.page
        return None


def _parse_text(path: Path) -> tuple[str, list[PageSpan], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, [PageSpan(1, 0, len(text))], "plaintext"


def _parse_pdfminer(path: Path) -> tuple[str, list[PageSpan], str]:
    from pdfminer.high_level import extract_text  # lazy

    parts: list[str] = []
    pages: list[PageSpan] = []
    cursor = 0
    # extract_text with page separators preserved so we can track page offsets
    full = extract_text(str(path))
    for i, page_text in enumerate(full.split("\f"), start=1):
        start = cursor
        parts.append(page_text)
        cursor += len(page_text)
        pages.append(PageSpan(i, start, cursor))
        # account for the form-feed we split on (except after the last page)
        cursor += 1
    text = "\f".join(parts)
    return text, pages, "pdfminer"


def _parse_docling(path: Path) -> tuple[str, list[PageSpan], str]:
    from docling.document_converter import DocumentConverter  # lazy

    conv = DocumentConverter()
    doc = conv.convert(str(path)).document
    text = doc.export_to_markdown()
    # Docling exposes provenance (page_no/bbox/charspan) per item; for the MVP we
    # keep the concatenated markdown as the coordinate system and treat it as one
    # page span. A precise charspan->page map is a documented enhancement.
    return text, [PageSpan(1, 0, len(text))], "docling"


_BACKENDS = {
    "plaintext": _parse_text,
    "pdfminer": _parse_pdfminer,
    "docling": _parse_docling,
}


def parse(path: Path, parser: str = "auto") -> ParsedDoc:
    path = Path(path)
    if parser == "auto":
        parser = "plaintext" if path.suffix.lower() in {".txt", ".md"} else "pdfminer"
    if parser not in _BACKENDS:
        raise ValueError(f"unknown parser {parser!r}; choose from {list(_BACKENDS)}")
    text, pages, backend = _BACKENDS[parser](path)
    return ParsedDoc(source_id=path.stem, text=text, backend=backend, pages=pages)
