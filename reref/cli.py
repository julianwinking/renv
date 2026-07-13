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

from . import db, experiment, log
from .cite import LATEX_PREAMBLE, append_sidecar, make_citation
from .config import Config, Lockfile
from .dataset import get_dataset, list_datasets, register_dataset
from .embed import get_embedder
from .indexer import build_index
from .project import Corpus, Project
from .retrieve import Retriever
from .store import Index
from .verify import get_verifier


def _resolve_project(corpus, ref: str) -> tuple[Path, str]:
    """Accept a project slug OR a path; return (root_path, slug). Uniform across commands."""
    p = Path(ref)
    if p.exists():
        return p, p.name
    return Path(corpus) / "projects" / ref, Path(ref).name


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
    proot, pslug = _resolve_project(args.corpus, args.project)
    project = Project(proot)
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
        # the citation table is the source of truth; citations.json is derived from it
        try:
            from . import ingest
            con = db.connect(args.corpus)
            db.project_id(con, pslug)
            row = ingest.record_citation(con, pslug, cit)
            sidecar = ingest.regenerate_sidecar(con, pslug, project.root)
            print(f"citation row: #{row['id']}"
                  + (f" → paper {best.record.source_id}" if row["paper_id"] else ""))
            print("sidecar (derived):", sidecar)
        except KeyError:
            # project not registered in the store — fall back to a plain sidecar
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
        proot, _ = _resolve_project(args.corpus, args.project)
        proj = Project(proot)
        print(f"project: {proj.root}")
        for name, p in [("src", proj.src), ("text", proj.text)]:
            mark = "✓" if p.exists() else "·"
            print(f"  {mark} {name}/")
        c = proj.citations_path
        print(f"  {'✓' if c.exists() else '·'} {c.name}")


def cmd_preamble(args):
    print(LATEX_PREAMBLE)


# --- the research store (Pillar 5: experiments + reasoning log) --------------
def _parse_params(pairs):
    """``--param k=v`` repeated -> dict; values JSON-decoded when possible."""
    import json as _json
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            sys.exit(f"! --param expects k=v, got {pair!r}")
        k, v = pair.split("=", 1)
        try:
            out[k] = _json.loads(v)
        except ValueError:
            out[k] = v
    return out


def _parse_evidence(spec):
    """``run:1,cite:2`` -> (runs, citations)."""
    runs, cites = [], []
    for tok in (spec or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        kind, _, num = tok.partition(":")
        if kind == "run":
            runs.append(int(num))
        elif kind in ("cite", "citation"):
            cites.append(int(num))
        else:
            sys.exit(f"! evidence must be run:<id> or cite:<id>, got {tok!r}")
    return runs, cites


def cmd_db_init(args):
    con = db.connect(args.corpus)
    print(f"env DB ready at {db.db_path(args.corpus)} (schema v{db.schema_version(con)})")


def cmd_export(args):
    con = db.connect(args.corpus)
    out = db.export(con, args.corpus, project=args.project)
    scope = f"project {args.project!r}" if args.project else "full env"
    print(f"exported {scope}: {len(db.TABLES)} tables -> {out}/")


def cmd_import(args):
    con = db.connect(args.corpus)
    n = db.import_jsonl(con, args.corpus, source=args.source)
    print(f"imported {n} rows from the JSONL export — DB rebuilt")


def cmd_project_new(args):
    con = db.connect(args.corpus)
    pid = db.ensure_project(con, args.slug, title=args.title)
    proj = Project(Path(args.corpus) / "projects" / args.slug)
    proj.ensure()
    (proj.root / "runs").mkdir(exist_ok=True)
    print(f"project {args.slug!r} (id {pid}) ready at {proj.root}/")


def cmd_exp_new(args):
    con = db.connect(args.corpus)
    e = experiment.create_experiment(
        con, args.project, args.slug, title=args.title,
        hypothesis=args.hypothesis, parent=args.parent,
    )
    edge = f" (parent {args.parent})" if args.parent else ""
    print(f"experiment {e['slug']!r}{edge} created [{e['status']}]")


def cmd_exp_list(args):
    con = db.connect(args.corpus)
    rows = experiment.list_experiments(con, args.project)
    if not rows:
        print("(no experiments yet)")
        return
    by_id = {r["id"]: r for r in rows}
    mark = {"planned": "·", "running": "▶", "done": "✓", "abandoned": "✗"}
    defs = experiment.metric_defs(con)
    for r in rows:
        depth = 0
        p = r["parent_id"]
        while p in by_id:
            depth += 1
            p = by_id[p]["parent_id"]
        metrics = "  ".join(f"{k}={experiment.fmt_metric(defs, k, v)}"
                            for k, v in (r["metrics"] or {}).items())
        print(f"{'  ' * depth}{mark.get(r['status'], '?')} {r['slug']}"
              f"  {r['title']}" + (f"   [{metrics}]" if metrics else ""))


def cmd_exp_run(args):
    con = db.connect(args.corpus)
    dataset_id = None
    if args.dataset:
        slug, _, ver = args.dataset.partition("@")
        ds = get_dataset(con, slug, ver or "1")
        if not ds:
            sys.exit(f"! dataset {args.dataset!r} not registered — `reref dataset add`")
        dataset_id = ds["id"]
    run = experiment.run_experiment(
        con, args.project, args.slug, entrypoint=args.entrypoint, root=args.corpus,
        params=_parse_params(args.param), dataset_id=dataset_id, seed=args.seed,
        env_allow=args.env_allow,
    )
    print(f"run {run['id']} [{run['status']}]  git={run['git_sha'] or '-'}  "
          f"seed={run['seed']}")
    defs = experiment.metric_defs(con)
    for m in experiment.get_metrics(con, run["id"]):
        split = f" ({m['split']})" if m["split"] else ""
        print(f"  {m['name']}{split} = {experiment.fmt_metric(defs, m['name'], m['value'])}")


def cmd_exp_ingest(args):
    con = db.connect(args.corpus)
    metrics = None
    if args.metrics:
        raw = Path(args.metrics[1:]).read_text() if args.metrics.startswith("@") else args.metrics
        metrics = json.loads(raw)
    dataset_id = None
    if args.dataset:
        slug, _, ver = args.dataset.partition("@")
        ds = get_dataset(con, slug, ver or "1")
        if not ds:
            sys.exit(f"! dataset {args.dataset!r} not registered — `reref dataset add`")
        dataset_id = ds["id"]
    try:
        run = experiment.ingest_run(con, args.project, args.slug, run_dir=args.dir,
                                    metrics=metrics, remote=args.remote,
                                    dataset_id=dataset_id)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        sys.exit(f"! {exc}")
    print(f"run {run['id']} ingested [{run['provenance']}]"
          + (f"  remote={run['remote']}" if run["remote"] else ""))
    defs = experiment.metric_defs(con)
    for m in experiment.get_metrics(con, run["id"]):
        print(f"  {m['name']} = {experiment.fmt_metric(defs, m['name'], m['value'])}")


def cmd_exp_show(args):
    con = db.connect(args.corpus)
    e = experiment.get_experiment(con, args.project, args.slug)
    if not e:
        sys.exit(f"! no experiment {args.slug!r} in {args.project!r}")
    print(f"{e['slug']}  [{e['status']}]  {e['title']}")
    if e["hypothesis"]:
        print(f"  hypothesis: {e['hypothesis']}")
    defs = experiment.metric_defs(con)
    for run in experiment.list_runs(con, e["id"]):
        print(f"  run {run['id']} [{run['status']}] {run['started']}  "
              f"git={run['git_sha'] or '-'}")
        for m in experiment.get_metrics(con, run["id"]):
            print(f"      {m['name']} = {experiment.fmt_metric(defs, m['name'], m['value'])}")


def cmd_log_add(args):
    con = db.connect(args.corpus)
    runs, cites = _parse_evidence(args.evidence)
    try:
        e = log.add_entry(con, args.project, args.type, args.body,
                          experiment=args.exp, runs=runs, citations=cites,
                          answers=args.answers, source=args.source)
    except ValueError as exc:
        sys.exit(f"! {exc}")
    print(f"logged [{e['type']}] #{e['id']} at {e['ts']}")


def cmd_log_edit(args):
    con = db.connect(args.corpus)
    try:
        e = log.update_entry(con, args.id, args.body)
    except KeyError as exc:
        sys.exit(f"! {exc}")
    print(f"edited [{e['type']}] #{e['id']}  (created {e['ts']}, edited {e['edited']})")


def cmd_log_list(args):
    con = db.connect(args.corpus)
    for e in reversed(log.list_entries(con, args.project, limit=args.limit)):
        ev = e["evidence"]
        tail = ""
        if ev["runs"] or ev["citations"]:
            tail = "  ⟵ " + " ".join(
                [f"run:{r}" for r in ev["runs"]] + [f"cite:{c}" for c in ev["citations"]]
            )
        head = e["body_md"].splitlines()[0] if e["body_md"] else ""
        mark = f" <{e['source']}>" if e.get("source") else ""
        if e["type"] == "question":
            mark += f" (answered by #{e['answered_by']})" if e.get("answered_by") else " (open)"
        elif e.get("answers"):
            mark += f" (answers #{e['answers']})"
        print(f"{e['ts']}  [{e['type']}]{mark} {head}{tail}")


def cmd_log_check(args):
    con = db.connect(args.corpus)
    violations = log.check_invariants(con)
    if not violations:
        print("✓ invariants hold (every result entry traces to a run)")
        return
    for v in violations:
        print(f"✗ {v['kind']}: log_entry #{v['log_entry_id']} — {v['detail']}")
    sys.exit(1)


def cmd_note_add(args):
    con = db.connect(args.corpus)
    n = log.add_note(con, args.project, args.body, title=args.title)
    print(f"note #{n['id']} saved at {n['ts']}")


def cmd_dataset_add(args):
    con = db.connect(args.corpus)
    ds = register_dataset(con, args.slug, version=args.version, path=args.path,
                          description=args.description, location=args.remote,
                          sha256=args.sha256)
    print(f"dataset {ds['slug']}@{ds['version']} (id {ds['id']}) "
          f"sha={ds['sha256'][:12] + '…' if ds['sha256'] else '-'}"
          + (f"  at {ds['location']}" if ds.get("location") else ""))


def cmd_dataset_list(args):
    con = db.connect(args.corpus)
    for d in list_datasets(con):
        print(f"  {d['slug']}@{d['version']}  {d['description'] or ''}")


def cmd_metric_define(args):
    con = db.connect(args.corpus)
    d = experiment.define_metric(
        con, args.name, label=args.label, unit=args.unit,
        direction=args.direction, fmt=args.fmt, description=args.description)
    arrow = {"maximize": "↑", "minimize": "↓", "info": "·"}[d["direction"]]
    print(f"metric {d['name']} {arrow}  label={d['label'] or d['name']}  "
          f"fmt={d['fmt']}" + (f"  unit={d['unit']}" if d["unit"] else ""))


def cmd_metric_list(args):
    con = db.connect(args.corpus)
    defs = experiment.metric_defs(con)
    if not defs:
        print("(no metric definitions — `reref metric define <name>`)")
        return
    arrow = {"maximize": "↑", "minimize": "↓", "info": "·"}
    for d in defs.values():
        print(f"  {d['name']} {arrow[d['direction']]}  {d['label'] or ''}"
              + (f"  [{d['unit']}]" if d["unit"] else "")
              + (f"  — {d['description']}" if d["description"] else ""))


def cmd_plan_add(args):
    from . import plan
    con = db.connect(args.corpus)
    kind = "milestone" if args.milestone else "deadline" if args.deadline else "phase"
    try:
        it = plan.add_item(con, args.project, args.title, due=args.due,
                           kind=kind, start=args.start, note=args.note,
                           end_deadline=args.end_deadline, parent_id=args.parent)
    except (ValueError, KeyError) as exc:
        sys.exit(f"! {exc}")
    span = f"{it['start']} → {it['due']}" if it["start"] else it["due"]
    tail = "  (ends in a deadline)" if it["end_deadline"] else ""
    print(f"plan #{it['id']} [{it['kind']}] {it['title']}  ({span}){tail}")


def cmd_plan_list(args):
    from . import plan
    con = db.connect(args.corpus)
    items = plan.list_items(con, args.project)
    if not items:
        print("(no plan yet — `reref plan add <project> \"<title>\" --due YYYY-MM-DD`)")
        return
    today = db.now()[:10]
    for it in items:
        mark = ("✓" if it["status"] == "done"
                else "!" if it["due"] < today else "·")
        span = f"{it['start']} → {it['due']}" if it["start"] else f"      due {it['due']}"
        print(f"  {mark} #{it['id']} [{it['kind']:9}] {span}  {it['title']}")


def cmd_plan_prepared(args):
    from . import plan
    con = db.connect(args.corpus)
    try:
        it = plan.update_item(con, args.id, prepared=0 if args.undo else 1)
    except (ValueError, KeyError) as exc:
        sys.exit(f"! {exc}")
    print(f"plan #{it['id']} {'prepared' if it['prepared'] else 'not prepared'}: {it['title']}")


def cmd_plan_done(args):
    from . import plan
    con = db.connect(args.corpus)
    try:
        it = plan.update_item(con, args.id, status="done")
    except (ValueError, KeyError) as exc:
        sys.exit(f"! {exc}")
    print(f"plan #{it['id']} done: {it['title']}")


def cmd_plan_rm(args):
    from . import plan
    con = db.connect(args.corpus)
    try:
        plan.delete_item(con, args.id)
    except KeyError as exc:
        sys.exit(f"! {exc}")
    print(f"plan #{args.id} removed")


def cmd_remote_add(args):
    from . import remote
    con = db.connect(args.corpus)
    try:
        r = remote.add_remote(con, args.name, host=args.host,
                              data_root=args.data_root, description=args.description)
    except ValueError as exc:
        sys.exit(f"! {exc}")
    print(f"remote {r['name']}  host={r['host']}"
          + (f"  data-root={r['data_root']}" if r["data_root"] else ""))


def cmd_remote_list(args):
    from . import remote
    con = db.connect(args.corpus)
    rows = remote.list_remotes(con)
    if not rows:
        print("(no remotes — `reref remote add snaga --data-root /scratch/you/research`)")
        return
    for r in rows:
        print(f"  {r['name']}  host={r['host'] or '(this machine)'}"
              + (f"  data-root={r['data_root']}" if r["data_root"] else "")
              + (f"  — {r['description']}" if r["description"] else ""))


def cmd_remote_rm(args):
    from . import remote
    con = db.connect(args.corpus)
    try:
        remote.delete_remote(con, args.name)
    except KeyError as exc:
        sys.exit(f"! {exc}")
    print(f"remote {args.name} removed")


def cmd_new(args):
    """Scaffold a project from templates/project/, register it, and git-init its repo."""
    from . import authoring
    import subprocess
    con = db.connect(args.corpus)
    title = args.title or args.slug
    pid = db.ensure_project(con, args.slug, title=title)
    root = Path(args.corpus) / "projects" / args.slug
    written = authoring.scaffold_from_template(args.corpus, args.slug, title)
    print(f"project {args.slug!r} (id {pid}) scaffolded at {root}/")
    print(f"  files: {', '.join(sorted(p.name for p in written)) or '(all already existed)'}")
    if authoring.seed_ideation(con, args.slug):
        print("  plan: seeded an open ideation question — thesis/contributions go in as "
              "claims, risks as questions (`reref claim add`, `reref log add`)")

    # each project is its own git repo (the env repo gitignores projects/*)
    if not args.no_git and not (root / ".git").exists():
        try:
            subprocess.run(["git", "init", "-q"], cwd=str(root), timeout=10, check=True)
            print(f"  git: initialized a repo in {root}/  "
                  f"— link a remote: `git -C {root} remote add origin <url>`")
        except Exception:
            print("  git: init skipped (git unavailable)")


def cmd_draft(args):
    from . import authoring
    con = db.connect(args.corpus)
    db.project_id(con, args.project)
    root = Path(args.corpus) / "projects" / args.project
    title = args.title or args.project
    written = authoring.scaffold_paper(root, args.project, title)
    print("paper skeleton:", ", ".join(str(p) for p in written))


def cmd_weave(args):
    from . import authoring
    con = db.connect(args.corpus)
    root = Path(args.corpus) / "projects" / args.project
    for p in authoring.weave(con, args.project, root):
        print("generated:", p)


def cmd_add(args):
    from . import ingest
    con = db.connect(args.corpus)
    res = ingest.add(con, args.corpus, args.source, key=args.key, download=args.download)
    p = res["paper"]
    print(f"paper {p['key']!r} ({res['kind']}): {p['title']}")
    if p["authors_json"]:
        import json as _j
        auth = _j.loads(p["authors_json"])
        print(f"  {', '.join(auth[:4])}{' …' if len(auth) > 4 else ''}  ({p['year'] or '?'})")
    if res["landed"]:
        print(f"  landed in library: {res['landed']}  — run `reref index` to retrieve it")


def cmd_discover(args):
    from . import ingest
    results = ingest.search_arxiv(args.query, max_results=args.limit)
    for i, r in enumerate(results):
        print(f"[{i}] {r['title']}  ({r['year'] or '?'})  arXiv:{r['arxiv']}")
        print(f"     {', '.join(r['authors'][:3])}{' …' if len(r['authors']) > 3 else ''}")
    if args.add is not None:
        if not 0 <= args.add < len(results):
            sys.exit(f"! --add {args.add} out of range")
        con = db.connect(args.corpus)
        paper = ingest.add_paper(con, results[args.add])
        print(f"added paper {paper['key']!r}")


def cmd_papers(args):
    from . import ingest
    con = db.connect(args.corpus)
    if args.uses:
        u = ingest.paper_usage(con, args.uses)
        if not u["paper"]:
            sys.exit(f"! no paper {args.uses!r}")
        print(f"{u['paper']['key']}: {u['paper']['title']}")
        print(f"  cited in {len(u['cited_in'])} place(s):")
        for c in u["cited_in"]:
            loc = c["manuscript_loc"] or "—"
            print(f"    [{c['support']}] {c['project']} @ {loc}: “{(c['quote'] or '')[:50]}…”")
        print(f"  used in {len(u['used_in_log'])} log entr(ies)")
        return
    for p in ingest.list_papers(con):
        print(f"  {p['key']}  ({p['year'] or '?'})  {p['title']}")


def cmd_card(args):
    from . import extract
    con = db.connect(args.corpus)
    card = extract.get_card(con, args.key)
    if not card or args.refresh:
        card = extract.extract_card(con, args.corpus, args.key)
    for field, v in card.items():
        print(f"[{field}] {v['text']}")


def cmd_extract(args):
    from . import extract
    con = db.connect(args.corpus)
    if args.all:
        for key, card in extract.extract_all(con, args.corpus).items():
            n = len(card) if "skipped" not in card else 0
            print(f"  {key}: {n} field(s)" + (f"  ({card['skipped']})" if not n else ""))
    else:
        card = extract.extract_card(con, args.corpus, args.key)
        print(f"{args.key}: extracted {len(card)} field(s) — {', '.join(card)}")


def cmd_bib(args):
    """Print BibTeX for the whole corpus (paper table)."""
    from . import ingest
    import json as _j
    con = db.connect(args.corpus)
    for p in ingest.list_papers(con):
        authors = " and ".join(_j.loads(p["authors_json"] or "[]")) or "Unknown"
        print(f"@article{{{p['key']},\n  title = {{{p['title'] or ''}}},\n"
              f"  author = {{{authors}}},\n  year = {{{p['year'] or ''}}},\n"
              f"  doi = {{{p['doi'] or ''}}}\n}}\n")


def cmd_review(args):
    from . import review
    con = db.connect(args.corpus)
    res = review.review(con, args.corpus, args.project)
    print(review.render_report(args.project, res["open"], res["suppressed"]), end="")
    print(f"(report saved: {res['report']})")
    if any(f["severity"] == "high" for f in res["open"]):
        sys.exit(1)


def cmd_finding_list(args):
    from . import finding
    con = db.connect(args.corpus)
    rows = finding.list_findings(con, args.project, status=args.status)
    if not rows:
        print("(no findings)")
        return
    for f in rows:
        print(f"#{f['id']} [{f['status']}] {f['severity']}/{f['check_id']}: {f['issue']}")


def cmd_finding_show(args):
    from . import finding
    con = db.connect(args.corpus)
    f = finding.get_finding(con, args.id)
    if not f:
        sys.exit(f"! no finding #{args.id}")
    print(f"#{f['id']} [{f['status']}] {f['severity']}  {f['check_id']} ({f['dimension']})")
    print(f"  issue: {f['issue']}")
    if f["location"]:
        print(f"  proof/reference: {f['location']}")
    for ev in f["evidence"]:
        ref = ev.get("citation_id") and f"citation #{ev['citation_id']}" or \
              ev.get("run_id") and f"run #{ev['run_id']}" or f"claim #{ev.get('claim_id')}"
        print(f"  ↳ branch into evidence: {ref}  {ev.get('note') or ''}")
    if f["adjudications"]:
        print("  verdict history (visible to future agents):")
        for a in f["adjudications"]:
            print(f"    [{a['verdict']}] by {a['by']} @ {a['ts']}: {a['reasoning']}")
    from . import refs
    fixes = refs.code_refs_for(con, args.corpus, "finding", str(args.id))
    if fixes:
        print("  fixed/referenced in code:")
        for r in fixes:
            rel = f" ({r['relation']})" if r["relation"] else ""
            print(f"    {r['file']}:{r['line']}{rel}  {r['text']}")


def cmd_finding_adjudicate(args, verdict):
    from . import finding
    con = db.connect(args.corpus)
    try:
        f = finding.adjudicate(con, args.id, verdict, args.reason, by=args.by)
    except (ValueError, KeyError) as exc:
        sys.exit(f"! {exc}")
    print(f"#{f['id']} → {f['status']}  (reason recorded; future reviews won't re-raise it)")


def cmd_claim_add(args):
    from . import claim
    con = db.connect(args.corpus)
    c = claim.add_claim(con, args.project, args.text, kind=args.kind, manuscript_loc=args.loc)
    print(f"claim #{c['id']} [{c['kind']}, {c['status']}]: {c['text']}")


def cmd_claim_link(args):
    from . import claim
    con = db.connect(args.corpus)
    try:
        c = claim.link_evidence(con, args.id, citation_id=args.cite, run_id=args.run,
                                stance=args.stance, note=args.note)
    except (ValueError, KeyError) as exc:
        sys.exit(f"! {exc}")
    print(f"claim #{c['id']} → {c['status']}  ({len(c['evidence'])} evidence)")


def cmd_claim_relate(args):
    from . import claim
    con = db.connect(args.corpus)
    try:
        c = claim.relate(con, args.id, args.related, kind=args.kind)
    except (ValueError, KeyError) as exc:
        sys.exit(f"! {exc}")
    print(f"claim #{args.id} {args.kind} #{args.related}  ({len(c['relations'])} relations)")


def cmd_claim_list(args):
    from . import claim
    con = db.connect(args.corpus)
    rows = claim.list_claims(con, args.project, status=args.status)
    if not rows:
        print("(no claims)")
        return
    mark = {"open": "○", "supported": "✓", "refuted": "✗"}
    for c in rows:
        print(f"#{c['id']} {mark.get(c['status'], '?')} [{c['kind']}] {c['text']}  "
              f"({c['evidence_count']} evidence)")


def cmd_claim_show(args):
    from . import claim
    con = db.connect(args.corpus)
    c = claim.get_claim(con, args.id)
    if not c:
        sys.exit(f"! no claim #{args.id}")
    print(f"#{c['id']} [{c['kind']}, {c['status']}] {c['text']}")
    for ev in c["evidence"]:
        ref = (f"citation #{ev['citation_id']}" if ev["citation_id"]
               else f"run #{ev['run_id']}")
        print(f"  ↳ {ev['stance']}: {ref}  {ev['note'] or ''}")


def cmd_exp_status(args):
    con = db.connect(args.corpus)
    experiment.set_status(con, args.project, args.slug, args.status)
    print(f"{args.slug} → {args.status}")


def cmd_refs_scan(args):
    from . import refs
    con = db.connect(args.corpus)
    for r in refs.validate(con, refs.scan(args.corpus)):
        mark = "ok" if r["resolves"] else "DANGLING"
        rel = f":{r['relation']}" if r["relation"] else ""
        print(f"  [{mark}] {r['file']}:{r['line']}  @reref:{r['kind']}:{r['id']}{rel}  {r['text']}")


def cmd_refs_check(args):
    from . import refs
    con = db.connect(args.corpus)
    dangling = [r for r in refs.validate(con, refs.scan(args.corpus)) if not r["resolves"]]
    if not dangling:
        print("✓ all @reref tags resolve to a store entity")
        return
    for r in dangling:
        print(f"✗ {r['file']}:{r['line']}  @reref:{r['kind']}:{r['id']} does not exist")
    sys.exit(1)


def cmd_refs_where(args):
    from . import refs
    hits = refs.code_refs_for(db.connect(args.corpus), args.corpus, args.kind, args.id)
    if not hits:
        print(f"(no code references to {args.kind}:{args.id})")
        return
    for r in hits:
        rel = f" ({r['relation']})" if r["relation"] else ""
        print(f"  {r['file']}:{r['line']}{rel}  {r['text']}")


def cmd_refs_strip(args):
    from . import refs
    for f in args.files:
        refs.strip_path(Path(f), in_place=args.in_place)
        print(("stripped " if args.in_place else "would strip ") + f)


def cmd_search(args):
    from . import search as searchmod
    con = db.connect(args.corpus)
    hits = searchmod.search(con, args.query, project=args.project, limit=args.limit)
    if not hits:
        print("(no matches)")
        return
    for h in hits:
        proj = f" {h['project']}" if h.get("project") else ""
        print(f"  [{h['kind']}{proj}] {h['title']}: {h['snippet']}")


def cmd_web(args):
    from . import web as webmod
    if args.action == "install":
        try:
            plist = webmod.install_launch_agent(
                args.corpus, domain=args.domain, port=args.domain_port,
                idle=args.idle_exit or 1800, https=args.https)
        except Exception as exc:
            sys.exit(f"! launchd install failed: {exc}")
        print(f"launchd agent loaded ({plist})")
        print(f"  on-demand: starts on the first request, exits after {args.idle_exit or 1800}s idle")
        hosts = Path("/etc/hosts").read_text() if Path("/etc/hosts").exists() else ""
        if args.domain not in hosts:
            print(f"  manual step (sudo, we never edit /etc/hosts silently):")
            print(f"    echo '127.0.0.1 {args.domain}' | sudo tee -a /etc/hosts")
        if args.https:
            print("  manual step (once, keychain prompt) so browsers trust the local CA:")
            print("    mkcert -install")
            print(f"  then: https://{args.domain}/  (http redirects)")
        else:
            print(f"  then: http://{args.domain}"
                  + (f":{args.domain_port}" if args.domain_port != 80 else "") + "/")
        return
    if args.action == "uninstall":
        removed = webmod.uninstall_launch_agent()
        print("launchd agent removed" if removed else "no launchd agent installed")
        return
    webmod.serve(args.corpus, port=args.port, host=args.host,
                 idle_exit=args.idle_exit if args.idle_exit > 0 else None,
                 launchd=args.launchd, tls_cert=args.tls_cert,
                 tls_key=args.tls_key, domain=args.domain)


def cmd_mcp(args):
    from .mcp_server import serve
    serve(args.corpus)


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

    # --- research store: experiments + reasoning log ---
    pdb = sub.add_parser("db", help="env database").add_subparsers(dest="db_cmd", required=True)
    pdb.add_parser("init", help="create/migrate the env DB").set_defaults(func=cmd_db_init)

    pex = sub.add_parser("export", help="write deterministic JSONL snapshot for git")
    pex.add_argument("--project", default=None, help="export only this project's slice")
    pex.set_defaults(func=cmd_export)

    pim = sub.add_parser("import", help="rebuild the DB from a JSONL export (inverse of export)")
    pim.add_argument("--source", default=None, help="export dir (default .research/export)")
    pim.set_defaults(func=cmd_import)

    pproj = sub.add_parser("project", help="project workspaces").add_subparsers(
        dest="project_cmd", required=True)
    pn = pproj.add_parser("new", help="create a project (DB row + workspace dirs)")
    pn.add_argument("slug")
    pn.add_argument("--title", default=None)
    pn.set_defaults(func=cmd_project_new)

    pe = sub.add_parser("exp", help="experiments (the DAG)").add_subparsers(
        dest="exp_cmd", required=True)
    en = pe.add_parser("new", help="create an experiment")
    en.add_argument("project")
    en.add_argument("slug")
    en.add_argument("--title", default=None)
    en.add_argument("--hypothesis", default=None)
    en.add_argument("--parent", default=None, help="parent experiment slug (DAG edge)")
    en.set_defaults(func=cmd_exp_new)
    el = pe.add_parser("list", help="show the experiment DAG + statuses")
    el.add_argument("project")
    el.set_defaults(func=cmd_exp_list)
    er = pe.add_parser("run", help="execute an entrypoint and record a run")
    er.add_argument("project")
    er.add_argument("slug")
    er.add_argument("--entrypoint", required=True, help="python file to run")
    er.add_argument("--param", action="append", help="k=v (repeatable)")
    er.add_argument("--dataset", default=None, help="slug[@version]")
    er.add_argument("--seed", type=int, default=0)
    er.add_argument("--env-allow", action="append", dest="env_allow",
                    help="pass a secret-named env var through to the run (repeatable)")
    er.set_defaults(func=cmd_exp_run)
    ei = pe.add_parser("ingest", help="register a run executed elsewhere (a cluster)")
    ei.add_argument("project")
    ei.add_argument("slug")
    ei.add_argument("--dir", default=None,
                    help="copied-back run directory (metrics.json [+ provenance.json])")
    ei.add_argument("--metrics", default=None,
                    help='final scalars when nothing is local: JSON or @file, e.g. \'{"acc":0.91}\'')
    ei.add_argument("--remote", default=None,
                    help="where the run/artifacts live, e.g. ssh://cluster/scratch/runs/exp42")
    ei.add_argument("--dataset", default=None, help="slug[@version]")
    ei.set_defaults(func=cmd_exp_ingest)
    es = pe.add_parser("show", help="experiment detail + its runs")
    es.add_argument("project")
    es.add_argument("slug")
    es.set_defaults(func=cmd_exp_show)
    est = pe.add_parser("status", help="set an experiment's status (e.g. abandon)")
    est.add_argument("project")
    est.add_argument("slug")
    est.add_argument("status", choices=["planned", "running", "done", "abandoned"])
    est.set_defaults(func=cmd_exp_status)

    pl = sub.add_parser("log", help="decision/reasoning log").add_subparsers(
        dest="log_cmd", required=True)
    la = pl.add_parser("add", help="append a typed log entry")
    la.add_argument("project")
    la.add_argument("type", choices=log.ENTRY_TYPES)
    la.add_argument("body")
    la.add_argument("--exp", default=None, help="related experiment slug")
    la.add_argument("--evidence", default=None, help="run:1,cite:2")
    la.add_argument("--answers", type=int, default=None,
                    help="id of the open question this entry answers")
    la.add_argument("--source", default=None,
                    help='who wrote it, e.g. "advisor: Prof. X" (feedback entries)')
    la.set_defaults(func=cmd_log_add)
    le = pl.add_parser("edit", help="edit an entry's prose (stamps last-edited)")
    le.add_argument("id", type=int)
    le.add_argument("body")
    le.set_defaults(func=cmd_log_edit)
    ll = pl.add_parser("list", help="recent log entries")
    ll.add_argument("project")
    ll.add_argument("--limit", type=int, default=50)
    ll.set_defaults(func=cmd_log_list)
    lc = pl.add_parser("check", help="audit §0 invariants")
    lc.set_defaults(func=cmd_log_check)

    pnote = sub.add_parser("note", help="meeting notes").add_subparsers(
        dest="note_cmd", required=True)
    na = pnote.add_parser("add", help="add a meeting note")
    na.add_argument("project")
    na.add_argument("body")
    na.add_argument("--title", default=None)
    na.set_defaults(func=cmd_note_add)

    pds = sub.add_parser("dataset", help="evaluation datasets").add_subparsers(
        dest="dataset_cmd", required=True)
    da = pds.add_parser("add", help="register a versioned, hashed dataset")
    da.add_argument("slug")
    da.add_argument("--version", default="1")
    da.add_argument("--path", default=None, help="local file to hash for provenance")
    da.add_argument("--remote", default=None,
                    help="where the data lives when not local, e.g. ssh://cluster/data/x")
    da.add_argument("--sha256", default=None,
                    help="hash computed remotely (`shasum -a 256` on the cluster)")
    da.add_argument("--description", default=None)
    da.set_defaults(func=cmd_dataset_add)
    dl = pds.add_parser("list", help="list datasets")
    dl.set_defaults(func=cmd_dataset_list)

    prm = sub.add_parser("remote", help="named clusters/storage (references your ssh aliases)").add_subparsers(
        dest="remote_cmd", required=True)
    ra = prm.add_parser("add", help="register a remote, e.g. `remote add snaga --data-root /scratch/you`")
    ra.add_argument("name")
    ra.add_argument("--host", default=None, help="ssh alias (default: the name — `ssh snaga` must work)")
    ra.add_argument("--data-root", default=None,
                    help="default experiment-data root there; makes `snaga:runs/x` locators expand")
    ra.add_argument("--description", default=None)
    ra.set_defaults(func=cmd_remote_add)
    rl = prm.add_parser("list", help="list remotes")
    rl.set_defaults(func=cmd_remote_list)
    rr = prm.add_parser("rm", help="remove a remote")
    rr.add_argument("name")
    rr.set_defaults(func=cmd_remote_rm)

    ppl = sub.add_parser("plan", help="project plan: phases + deadlines (Gantt)").add_subparsers(
        dest="plan_cmd", required=True)
    pa = ppl.add_parser("add", help="add a phase or milestone")
    pa.add_argument("project")
    pa.add_argument("title")
    pa.add_argument("--due", required=True, help="YYYY-MM-DD (end date / the deadline)")
    pa.add_argument("--start", default=None, help="YYYY-MM-DD (phases)")
    pa.add_argument("--milestone", action="store_true", help="a single-date event")
    pa.add_argument("--deadline", action="store_true",
                    help="a single-date DEADLINE (can be marked prepared)")
    pa.add_argument("--end-deadline", action="store_true",
                    help="this phase ends in a deadline")
    pa.add_argument("--parent", type=int, default=None,
                    help="id of the phase this is a sub-item of")
    pa.add_argument("--note", default=None)
    pa.set_defaults(func=cmd_plan_add)
    pll = ppl.add_parser("list", help="the plan, date-ordered")
    pll.add_argument("project")
    pll.set_defaults(func=cmd_plan_list)
    pd = ppl.add_parser("done", help="mark an item done")
    pd.add_argument("id", type=int)
    pd.set_defaults(func=cmd_plan_done)
    pp = ppl.add_parser("prepared", help="mark a deadline prepared (--undo to revert)")
    pp.add_argument("id", type=int)
    pp.add_argument("--undo", action="store_true")
    pp.set_defaults(func=cmd_plan_prepared)
    pr = ppl.add_parser("rm", help="remove an item (plans are intent, not evidence)")
    pr.add_argument("id", type=int)
    pr.set_defaults(func=cmd_plan_rm)

    pmet = sub.add_parser("metric", help="metric definitions (standardized display)").add_subparsers(
        dest="metric_cmd", required=True)
    md = pmet.add_parser("define", help="register/update how a metric renders everywhere")
    md.add_argument("name")
    md.add_argument("--label", default=None, help="display label (default: the name)")
    md.add_argument("--unit", default=None, help="unit suffix, e.g. %% or ms")
    md.add_argument("--direction", default="maximize",
                    choices=["maximize", "minimize", "info"],
                    help="is bigger better? (info = neither)")
    md.add_argument("--fmt", default=".3f", help="python format spec (default .3f)")
    md.add_argument("--description", default=None)
    md.set_defaults(func=cmd_metric_define)
    ml = pmet.add_parser("list", help="list metric definitions")
    ml.set_defaults(func=cmd_metric_list)

    pnew = sub.add_parser("new", help="scaffold a project from templates/project/ (+ git init)")
    pnew.add_argument("slug")
    pnew.add_argument("--title", default=None)
    pnew.add_argument("--no-git", action="store_true", help="don't git-init the project repo")
    pnew.set_defaults(func=cmd_new)

    pdr = sub.add_parser("draft", help="(re)scaffold the paper skeleton under text/")
    pdr.add_argument("project")
    pdr.add_argument("--title", default=None)
    pdr.set_defaults(func=cmd_draft)

    pw = sub.add_parser("weave", help="regenerate results_table.tex + references.bib from the store")
    pw.add_argument("project")
    pw.set_defaults(func=cmd_weave)

    # --- ingest + knowledge base ---
    pa = sub.add_parser("add", help="ingest a paper (PDF path / arXiv id / DOI)")
    pa.add_argument("source")
    pa.add_argument("--key", default=None, help="override the derived citation key")
    pa.add_argument("--download", action="store_true", help="download arXiv PDF into library/")
    pa.set_defaults(func=cmd_add)

    pdisc = sub.add_parser("discover", help="search arXiv for relevant papers (literature discovery)")
    pdisc.add_argument("query")
    pdisc.add_argument("--limit", type=int, default=10)
    pdisc.add_argument("--add", type=int, default=None, help="ingest result N into the library")
    pdisc.set_defaults(func=cmd_discover)

    ppap = sub.add_parser("papers", help="list papers, or --uses <key> for the usage map")
    ppap.add_argument("--uses", default=None, help="show where a paper is cited/used")
    ppap.set_defaults(func=cmd_papers)

    pcard = sub.add_parser("card", help="show a paper's structured card (generates if missing)")
    pcard.add_argument("key")
    pcard.add_argument("--refresh", action="store_true", help="re-extract")
    pcard.set_defaults(func=cmd_card)

    pxt = sub.add_parser("extract", help="(re)build structured cards")
    pxt.add_argument("key", nargs="?", default=None)
    pxt.add_argument("--all", action="store_true")
    pxt.set_defaults(func=cmd_extract)

    pbib = sub.add_parser("bib", help="print BibTeX for the whole corpus")
    pbib.set_defaults(func=cmd_bib)

    prev = sub.add_parser("review", help="run automated per-section paper checks (Pillar 8)")
    prev.add_argument("project")
    prev.set_defaults(func=cmd_review)

    pf = sub.add_parser("finding", help="adjudicate review findings (accept/reject + reasoning)"
                        ).add_subparsers(dest="finding_cmd", required=True)
    fl = pf.add_parser("list", help="list a project's findings")
    fl.add_argument("project")
    fl.add_argument("--status", default=None,
                    choices=["open", "accepted", "rejected", "resolved"])
    fl.set_defaults(func=cmd_finding_list)
    fs = pf.add_parser("show", help="a finding + its evidence + verdict history")
    fs.add_argument("id", type=int)
    fs.set_defaults(func=cmd_finding_show)
    fa = pf.add_parser("accept", help="accept a finding (with reasoning)")
    fa.add_argument("id", type=int)
    fa.add_argument("--reason", required=True)
    fa.add_argument("--by", default="human")
    fa.set_defaults(func=lambda a: cmd_finding_adjudicate(a, "accept"))
    fr = pf.add_parser("reject", help="reject a finding so it is never re-raised (with reasoning)")
    fr.add_argument("id", type=int)
    fr.add_argument("--reason", required=True)
    fr.add_argument("--by", default="human")
    fr.set_defaults(func=lambda a: cmd_finding_adjudicate(a, "reject"))

    pcl = sub.add_parser("claim", help="the claim/evidence graph (assertions → citations/runs)"
                         ).add_subparsers(dest="claim_cmd", required=True)
    cla = pcl.add_parser("add", help="add a claim")
    cla.add_argument("project")
    cla.add_argument("text")
    cla.add_argument("--kind", default="assertion", choices=["thesis", "contribution", "assertion"])
    cla.add_argument("--loc", default=None, help="manuscript location")
    cla.set_defaults(func=cmd_claim_add)
    cll = pcl.add_parser("link", help="attach evidence (a citation or run) to a claim")
    cll.add_argument("id", type=int)
    cll.add_argument("--cite", type=int, default=None, help="citation id")
    cll.add_argument("--run", type=int, default=None, help="run id")
    cll.add_argument("--stance", default="supports", choices=["supports", "refutes"])
    cll.add_argument("--note", default=None)
    cll.set_defaults(func=cmd_claim_link)
    clr = pcl.add_parser("relate", help="chain claims (argument structure, not proof)")
    clr.add_argument("id", type=int)
    clr.add_argument("related", type=int)
    clr.add_argument("--kind", default="depends_on", choices=["depends_on", "contradicts"])
    clr.set_defaults(func=cmd_claim_relate)
    cll2 = pcl.add_parser("list", help="list claims + status")
    cll2.add_argument("project")
    cll2.add_argument("--status", default=None, choices=["open", "supported", "refuted"])
    cll2.set_defaults(func=cmd_claim_list)
    cls = pcl.add_parser("show", help="a claim + its evidence")
    cls.add_argument("id", type=int)
    cls.set_defaults(func=cmd_claim_show)

    pref = sub.add_parser("refs", help="code↔store cross-references (@reref tags)"
                          ).add_subparsers(dest="refs_cmd", required=True)
    rsc = pref.add_parser("scan", help="list all @reref tags + whether they resolve")
    rsc.set_defaults(func=cmd_refs_scan)
    rch = pref.add_parser("check", help="fail if any @reref tag is dangling")
    rch.set_defaults(func=cmd_refs_check)
    rwh = pref.add_parser("where", help="where a store entity is referenced in code")
    rwh.add_argument("kind", choices=["paper", "finding", "decision", "run",
                                      "claim", "dataset", "experiment"])
    rwh.add_argument("id")
    rwh.set_defaults(func=cmd_refs_where)
    rst = pref.add_parser("strip", help="remove @reref tags (for publication)")
    rst.add_argument("files", nargs="+")
    rst.add_argument("--in-place", action="store_true")
    rst.set_defaults(func=cmd_refs_strip)

    psr = sub.add_parser("search", help="full-text search the knowledge base (papers/cards/notes/log/claims)")
    psr.add_argument("query")
    psr.add_argument("--project", default=None, help="scope to one project")
    psr.add_argument("--limit", type=int, default=30)
    psr.set_defaults(func=cmd_search)

    pweb = sub.add_parser("web", help="the local web cockpit (serve, or install on-demand launchd start)")
    pweb.add_argument("action", nargs="?", default="serve",
                      choices=["serve", "install", "uninstall"],
                      help="install = launchd socket activation: starts on first "
                           "request at http://research.test, exits when idle")
    pweb.add_argument("--port", type=int, default=8765)
    pweb.add_argument("--host", default="127.0.0.1")
    pweb.add_argument("--idle-exit", type=int, default=0, metavar="SECONDS",
                      help="exit after this long without a request (0 = never)")
    pweb.add_argument("--launchd", action="store_true",
                      help="adopt the socket from launchd (used by the agent, not by hand)")
    pweb.add_argument("--domain", default="research.test",
                      help="local domain for install (.test is IETF-reserved; never a real TLD)")
    pweb.add_argument("--domain-port", type=int, default=80,
                      help="port the launchd socket listens on (80 → no :port in the URL)")
    pweb.add_argument("--https", action="store_true",
                      help="install with TLS on :443 (mkcert local CA) + :80 redirect")
    pweb.add_argument("--tls-cert", default=None, help=argparse.SUPPRESS)
    pweb.add_argument("--tls-key", default=None, help=argparse.SUPPRESS)
    pweb.set_defaults(func=cmd_web)

    pm = sub.add_parser("mcp", help="run the local stdio MCP server (for Claude Code)")
    pm.set_defaults(func=cmd_mcp)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
