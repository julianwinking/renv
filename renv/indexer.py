"""Build the index over a library folder and write the lockfile."""

from __future__ import annotations

from pathlib import Path

from .chunk import chunk_text
from .config import Config, Lockfile, SourceRecord, sha256_file
from .embed import get_embedder
from .parse import parse
from .selectors import build_anchor
from .store import Index, IndexRecord

SUPPORTED = {".txt", ".md", ".pdf"}


def build_index(library: Path, config: Config | None = None) -> tuple[Index, Lockfile]:
    library = Path(library)
    config = config or Config()

    files = sorted(p for p in library.rglob("*") if p.suffix.lower() in SUPPORTED)
    if not files:
        raise FileNotFoundError(f"no .txt/.md/.pdf files under {library}")

    sources: list[SourceRecord] = []
    all_chunks = []
    for f in files:
        parser = config.parser if config.parser != "plaintext" else "auto"
        doc = parse(f, parser=parser)
        chunks = chunk_text(
            doc.source_id, doc.text, mode=config.chunker,
            min_chars=config.chunk_min_chars, max_chars=config.chunk_max_chars,
            page_of=doc.page_of,
        )
        for ch in chunks:
            all_chunks.append((doc, ch))
        sources.append(SourceRecord(
            source_id=doc.source_id,
            path=str(f.relative_to(library)),
            sha256=sha256_file(f),
            n_chunks=len(chunks),
        ))

    embedder = get_embedder(config.embedder, config.embedder_model)
    texts = [ch.text for _, ch in all_chunks]
    embedder.fit(texts)
    vectors = embedder.encode(texts)

    records: list[IndexRecord] = []
    per_source_counter: dict[str, int] = {}
    for (doc, ch), vec in zip(all_chunks, vectors):
        cid = per_source_counter.get(ch.source_id, 0)
        per_source_counter[ch.source_id] = cid + 1
        anchor = build_anchor(doc.text, ch.start, ch.end, config.anchor_context_chars)
        records.append(IndexRecord(
            source_id=ch.source_id, chunk_id=cid, text=ch.text,
            start=ch.start, end=ch.end, page=ch.page,
            anchor=anchor.to_dict(), vector=vec,
        ))

    lock = Lockfile(config=config, sources=sources)
    index = Index(config_fingerprint=config.fingerprint(), records=records)
    return index, lock
