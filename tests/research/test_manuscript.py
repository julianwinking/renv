"""Manuscript domain: text/ sandbox, weave-compile, span-cite against the index."""

from __future__ import annotations

import json
import sys

from renv.config import Config
from renv.corpus.indexer import build_index
from renv.project import Corpus
from renv.research import authoring, db, experiment, manuscript
from renv.research.manuscript import GENERATED_NAMES


def _project(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="A Paper")
    root = tmp_path / "projects" / "p"
    authoring.scaffold_paper(root, "p", "A Paper")
    return con, root


def test_list_tree_flags_generated_and_hides_build_cruft(tmp_path):
    con, root = _project(tmp_path)
    text = root / "text"
    (text / "results_table.tex").write_text("% GENERATED\n")
    (text / "paper.aux").write_text("cruft")
    (text / "sections").mkdir()
    (text / "sections" / "intro.tex").write_text("% intro\n")
    tree = manuscript.list_tree(con, tmp_path, "p")
    names = {n["name"] for n in tree["tree"]}
    assert "paper.aux" not in names
    assert "sections" in names and "paper.tex" in names
    by = {n["name"]: n for n in tree["tree"]}
    assert by["results_table.tex"]["generated"] is True
    assert by["results_table.tex"]["writable"] is False
    assert by["paper.tex"]["writable"] is True
    intro = by["sections"]["children"][0]
    assert intro["path"] == "sections/intro.tex"


def test_path_traversal_is_refused(tmp_path):
    con, _ = _project(tmp_path)
    for bad in ("../AGENTS.md", "/etc/passwd", "foo/../../secret.tex"):
        try:
            manuscript.read_file(con, tmp_path, "p", bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError as e:
            assert "escapes" in str(e)


def test_write_read_roundtrip_and_mkdir(tmp_path):
    con, _ = _project(tmp_path)
    out = manuscript.write_file(con, tmp_path, "p", "sections/intro.tex",
                                "\\section{Intro}\n")
    assert out["saved"] == "sections/intro.tex"
    got = manuscript.read_file(con, tmp_path, "p", "sections/intro.tex")
    assert got["content"] == "\\section{Intro}\n"
    assert got["writable"] is True


def test_weave_outputs_are_not_writable(tmp_path):
    con, _ = _project(tmp_path)
    for name in GENERATED_NAMES:
        try:
            manuscript.write_file(con, tmp_path, "p", name, "hand typed")
            raise AssertionError(name)
        except ValueError as e:
            assert "weave" in str(e)


def test_delete_refuses_skeleton(tmp_path):
    con, _ = _project(tmp_path)
    try:
        manuscript.delete_file(con, tmp_path, "p", "paper.tex")
        raise AssertionError
    except ValueError:
        pass
    manuscript.write_file(con, tmp_path, "p", "notes.tex", "% x\n")
    assert manuscript.delete_file(con, tmp_path, "p", "notes.tex")["deleted"] == "notes.tex"


def test_parse_spancite_and_cite(tmp_path):
    tex = (r"Prior work \spancite{gao2023_alce}{10}{40}{citation precision} "
           r"and \cite{smith2024, jones2020}. \input{results_table}")
    parsed = manuscript.parse_tex_macros(tex)
    assert parsed["spancites"][0]["source_id"] == "gao2023_alce"
    assert parsed["spancites"][0]["start"] == 10
    assert "citation precision" in parsed["spancites"][0]["quote"]
    assert {c["key"] for c in parsed["cites"]} == {"smith2024", "jones2020"}
    assert parsed["inputs"][0]["name"] == "results_table"


def test_compile_without_engine_is_honest(tmp_path, monkeypatch):
    con, _ = _project(tmp_path)
    monkeypatch.setattr(manuscript, "detect_engine", lambda which=None: None)
    result = manuscript.compile_manuscript(con, tmp_path, "p", weave=False)
    assert result["ok"] is False and result["engine"] is None
    assert "latexmk" in result["tried"]
    assert "Install" in result["hint"]


def test_compile_with_stub_engine_writes_pdf(tmp_path):
    con, root = _project(tmp_path)
    stub = tmp_path / "fake_tex.py"
    stub.write_text(
        "from pathlib import Path\n"
        "Path('paper.pdf').write_bytes(b'%PDF-1.1\\ntrailer<<>>\\n%%EOF\\n')\n"
        "print('ok')\n")
    engine = {"name": "stub", "commands": [[sys.executable, str(stub)]]}
    result = manuscript.compile_manuscript(con, tmp_path, "p", weave=True, engine=engine)
    assert result["ok"] is True
    assert result["pdf"] is True
    assert "results_table.tex" in result["woven"]
    pdf = manuscript.pdf_bytes(con, tmp_path, "p")
    assert pdf.startswith(b"%PDF")


def test_writing_context_links_spancite_to_store_rows(tmp_path):
    con, root = _project(tmp_path)
    experiment.create_experiment(con, "p", "001")
    entry = tmp_path / "e.py"
    entry.write_text(
        "import json,os\n"
        "json.dump({'recall':0.8}, open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    experiment.run_experiment(con, "p", "001", entrypoint=str(entry), root=str(tmp_path))

    class _Cit:
        source_id = "gao2023_alce"
        claim = "citation precision uses NLI"
        start = 10
        end = 40
        quote = "citation precision"
        prefix = suffix = ""
        support = "full"
        support_score = 1.0
    from renv.papers import ingest
    row = ingest.record_citation(con, "p", _Cit())
    paper = root / "text" / "paper.tex"
    paper.write_text(paper.read_text() +
                     r"\spancite{gao2023_alce}{10}{40}{citation precision}" + "\n")
    ctx = manuscript.writing_context(con, tmp_path, "p")
    assert ctx["metrics"][0]["name"] == "recall"
    span = next(s for s in ctx["spancites"] if s["source_id"] == "gao2023_alce")
    assert span["in_store"] is True and span["citation_id"] == row["id"]
    assert span["support"] == "full"


def _index_demo(tmp_path):
    corpus = Corpus(tmp_path)
    corpus.library.mkdir(parents=True)
    (corpus.library / "alce.txt").write_text(
        "ALCE evaluates citation quality. Citation precision flags any cited passage "
        "that is irrelevant and does not support the statement, using a natural "
        "language inference model. Smaller passages are easier to verify.")
    index, lock = build_index(corpus.library, Config())
    corpus.ensure_artifacts()
    lock.save(corpus.artifacts)
    index.save(corpus.artifacts)
    return corpus


def test_cite_claim_returns_spancite_and_writes_row(tmp_path):
    con, _ = _project(tmp_path)
    _index_demo(tmp_path)
    claim = ("Citation precision flags a cited passage that does not support "
             "the statement using natural language inference.")
    preview = manuscript.cite_claim(con, tmp_path, claim, project="p", write=False)
    assert preview["found"] is True
    assert preview["latex"].startswith(r"\spancite{")
    assert preview["written"] is False
    assert preview["candidates"]
    written = manuscript.cite_claim(con, tmp_path, claim, project="p", write=True)
    assert written["written"] is True and written["citation_id"]
    sidecar = json.loads((tmp_path / "projects" / "p" / "citations.json").read_text())
    assert sidecar and sidecar[0]["source_id"] == written["source_id"]
