"""Integration test: a shared corpus + a project that cites it (no deps).

Run: python tests/test_pipeline.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renv.config import Config, Lockfile  # noqa: E402
from renv.corpus.cite import make_citation  # noqa: E402
from renv.corpus.embed import get_embedder  # noqa: E402
from renv.corpus.index_store import Index  # noqa: E402
from renv.corpus.indexer import build_index  # noqa: E402
from renv.corpus.retrieve import Retriever  # noqa: E402
from renv.corpus.selectors import resolve  # noqa: E402
from renv.corpus.verify import get_verifier  # noqa: E402
from renv.project import Corpus, Project  # noqa: E402

PAPER = (
    "ALCE evaluates citation quality. Citation precision flags any cited passage "
    "that is irrelevant and does not support the statement, using a natural "
    "language inference model. Smaller passages are easier to verify."
)


def test_shared_corpus_two_projects():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        # one shared corpus
        corpus = Corpus(root)
        corpus.library.mkdir(parents=True)
        (corpus.library / "alce.txt").write_text(PAPER)

        index, lock = build_index(corpus.library, Config())
        corpus.ensure_artifacts()
        lock.save(corpus.artifacts)
        index.save(corpus.artifacts)

        assert corpus.is_indexed()
        assert not (corpus.library / "renv.index.json").exists(), \
            "artifacts must NOT pollute library/"
        assert lock.sources[0].sha256, "lockfile must record a content hash"

        # reload like the CLI does
        lock2 = Lockfile.load(corpus.artifacts)
        index2 = Index.load(corpus.artifacts)
        assert index2.config_fingerprint == lock2.config.fingerprint()

        emb = get_embedder("lexical", "tfidf-builtin")
        emb.fit([r.text for r in index2.records])
        r = Retriever(index2, emb, get_verifier("lexical"))

        # two independent projects retrieve the SAME corpus
        hashes = {s.source_id: s.sha256 for s in lock2.sources}
        for name in ("paper-a", "paper-b"):
            proj = Project(root / "projects" / name)
            proj.ensure()
            cands = r.search(
                "Citation precision flags a cited passage that does not support "
                "the statement using natural language inference.", top_k=3)
            best = cands[0]
            assert best.verdict.support in {"full", "partial"}, best.verdict
            cit = make_citation("claim", best, hashes.get(best.record.source_id, ""))
            assert cit.source_sha256 == lock2.sources[0].sha256, "citation pins source"

            # the emitted anchor resolves back to the exact span
            anchor = index2.anchor_for(best.record)
            src_text = (corpus.library / "alce.txt").read_text()
            res = resolve(src_text, anchor)
            assert res is not None and res.score == 1.0
            assert src_text[res.start:res.end] == anchor.quote.exact


if __name__ == "__main__":
    test_shared_corpus_two_projects()
    print("ok: shared-corpus / multi-project integration test passed")
