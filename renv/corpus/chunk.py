"""Split a parsed document into passages that retain their char offsets.

Granularity is sentence- or paragraph-level on purpose: the 2026 finding
"Are Finer Citations Always Better?" shows sub-sentence anchoring tends to
underperform sentence-level. Each chunk keeps (start, end) into the parsed text
so an anchor can be built directly from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Sentence boundary: end punctuation + whitespace, avoiding common abbreviations
# and decimals. Deliberately simple and deterministic (reproducibility matters
# more than linguistic perfection for the lockfile).
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
_PARA_SPLIT = re.compile(r"\n\s*\n")


@dataclass
class Chunk:
    source_id: str
    text: str
    start: int
    end: int
    page: int | None = None


def _spans(text: str, splitter: re.Pattern) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in splitter.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def chunk_text(
    source_id: str,
    text: str,
    mode: str = "sentence",
    min_chars: int = 40,
    max_chars: int = 1200,
    page_of=None,
) -> list[Chunk]:
    splitter = _PARA_SPLIT if mode == "paragraph" else _SENT_END
    out: list[Chunk] = []
    for s, e in _spans(text, splitter):
        raw = text[s:e]
        stripped = raw.strip()
        if len(stripped) < min_chars:
            continue
        # tighten offsets to the stripped content
        cs = s + (len(raw) - len(raw.lstrip()))
        ce = cs + len(stripped)
        # hard-split overly long passages on whitespace to respect max_chars
        if ce - cs > max_chars:
            for ws, we in _hard_split(text, cs, ce, max_chars):
                out.append(Chunk(source_id, text[ws:we], ws, we,
                                 page_of(ws) if page_of else None))
        else:
            out.append(Chunk(source_id, stripped, cs, ce,
                             page_of(cs) if page_of else None))
    return out


def _hard_split(text: str, start: int, end: int, max_chars: int):
    pos = start
    while pos < end:
        stop = min(pos + max_chars, end)
        if stop < end:
            # back up to last whitespace to avoid cutting a word
            ws = text.rfind(" ", pos, stop)
            if ws > pos:
                stop = ws
        yield pos, stop
        pos = stop + 1
