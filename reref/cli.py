"""reref CLI — the engine: index a shared corpus, cite it from any project.

    reref index   [--corpus .]                     index <corpus>/library -> .reref/
    reref cite    "<claim>" <project> [--corpus .]  retrieve, verify, emit citation
    reref resolve "<claim>" [--corpus .]            show where a claim's span anchors
    reref status  [--corpus .] [project]            corpus + (optional) project state
    reref preamble                                  print the LaTeX \\spancite macro

One shared corpus (library/ + .reref/) at --corpus; many projects retrieve it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cite import LATEX_PREAMBLE, append_sidecar, make_citation
from .config import Config, Lockfile
from .embed import get_embedder
from .indexer import build_index
from .project import Corpus, Project
from .retrieve import Retriever
from .store import Index
from .verify import get_verifier


def _load(corpus: Corpus, verifier_name: str) -> tuple[Retriever, Lockfile]:
    if not corpus.is_indexed():
        sys.exit(f"! corpus at {corpus.root} is not indexed — run `reref index`")
    lock = Lockfile.load(corpus.artifacts)
    index = Index.load(corpus.artifacts)
    if index.config_fingerprint != lock.config.fingerprint():
        print("! warning: index fingerprint != lockfile config; re-run `reref index`",
              file=sys.stderr)
    embedder = get_embedder(lock.config.embedder, lock.config.embedder_model)
    if lock.config.embedder == "lexical":
        embedder.fit([r.text for r in index.records])  # idf needs the corpus
    return Retriever(index, embedder, get_verifier(verifier_name)), lock


def cmd_index(args):
    corpus = Corpus(args.corpus)
    corpus.validate()
    config = Config(
        parser=args.parser, chunker=args.chunker,
        embedder=args.embedder, embedder_model=args.model, top_k=args.top_k,
    )
    index, lock = build_index(corpus.library, config)
    corpus.ensure_artifacts()
    lock.save(corpus.artifacts)
    index.save(corpus.artifacts)
    print(f"indexed {len(lock.sources)} source(s), {len(index.records)} chunk(s)")
    print(f"  config fingerprint: {config.fingerprint()}")
    print(f"  shared corpus artifacts: {corpus.artifacts}/")


def cmd_cite(args):
    corpus = Corpus(args.corpus)
    project = Project(args.project)
    project.validate()
    r, lock = _load(corpus, args.verifier)
    hashes = {s.source_id: s.sha256 for s in lock.sources}
    cands = r.search(args.claim, top_k=args.top_k, verify=True)
    if not cands:
        sys.exit("no candidates")
    best = cands[0]
    cit = make_citation(args.claim, best, hashes.get(best.record.source_id, ""))
    print("CLAIM:", args.claim)
    print(f"SUPPORT: {cit.support} ({cit.support_score})  sim={cit.similarity}")
    print(f"SOURCE: {cit.source_id} chars {cit.start}-{cit.end} (page {cit.page})")
    print(f"QUOTE: “{cit.quote}”")
    print("LATEX:", cit.latex())
    if args.write:
        print("sidecar:", append_sidecar(project.root, cit,
                                         filename=project.citations_path.name))
    if args.all:
        print("\n-- other candidates --")
        for c in cands[1:]:
            v = c.verdict
            print(f"  [{v.support if v else '?'}] sim={c.similarity:.3f} "
                  f"{c.record.source_id}:{c.record.start}-{c.record.end} "
                  f"“{c.record.text[:80]}...”")


def cmd_resolve(args):
    corpus = Corpus(args.corpus)
    r, _ = _load(corpus, "lexical")
    best = r.search(args.claim, top_k=1, verify=False)[0]
    a = r.index.anchor_for(best.record)
    print(f"anchor for {best.record.source_id}:{best.record.start}-{best.record.end}")
    print(f"  exact:  “{a.quote.exact[:120]}”")
    print(f"  prefix: …{a.quote.prefix}")
    print(f"  suffix: {a.quote.suffix}…")


def cmd_status(args):
    corpus = Corpus(args.corpus)
    print(f"corpus: {corpus.root}")
    lib = "✓" if corpus.library.exists() else "·"
    n = len(list(corpus.library.glob("*"))) if corpus.library.exists() else 0
    print(f"  {lib} library/  ({n} file(s))")
    if corpus.is_indexed():
        lock = Lockfile.load(corpus.artifacts)
        idx = Index.load(corpus.artifacts)
        ok = "ok" if idx.config_fingerprint == lock.config.fingerprint() else "STALE"
        print(f"  ✓ indexed: {len(lock.sources)} source(s), {len(idx.records)} chunk(s) "
              f"[{ok}, fp {idx.config_fingerprint}]")
    else:
        print("  · not indexed")
    if args.project:
        proj = Project(args.project)
        print(f"project: {proj.root}")
        for name, p in [("src", proj.src), ("text", proj.text)]:
            mark = "✓" if p.exists() else "·"
            print(f"  {mark} {name}/")
        c = proj.citations_path
        print(f"  {'✓' if c.exists() else '·'} {c.name}")


def cmd_preamble(args):
    print(LATEX_PREAMBLE)


def main(argv=None):
    p = argparse.ArgumentParser(prog="reref")
    p.add_argument("--corpus", default=".", help="shared corpus root (library/ + .reref/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="index the shared corpus library")
    pi.add_argument("--parser", default="plaintext", choices=["plaintext", "pdfminer", "docling"])
    pi.add_argument("--chunker", default="sentence", choices=["sentence", "paragraph"])
    pi.add_argument("--embedder", default="lexical", choices=["lexical", "sentence-transformers"])
    pi.add_argument("--model", default="tfidf-builtin")
    pi.add_argument("--top-k", type=int, default=5)
    pi.set_defaults(func=cmd_index)

    pc = sub.add_parser("cite", help="cite the exact source span for a claim")
    pc.add_argument("claim")
    pc.add_argument("project")
    pc.add_argument("--verifier", default="lexical", choices=["lexical", "factcg"])
    pc.add_argument("--top-k", type=int, default=5)
    pc.add_argument("--all", action="store_true", help="show other candidates")
    pc.add_argument("--write", action="store_true", help="append to project citations.json")
    pc.set_defaults(func=cmd_cite)

    pr = sub.add_parser("resolve", help="show the anchor for a claim's best span")
    pr.add_argument("claim")
    pr.set_defaults(func=cmd_resolve)

    ps = sub.add_parser("status", help="corpus + optional project state")
    ps.add_argument("project", nargs="?", default=None)
    ps.set_defaults(func=cmd_status)

    pp = sub.add_parser("preamble", help="print LaTeX \\spancite definition")
    pp.set_defaults(func=cmd_preamble)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
