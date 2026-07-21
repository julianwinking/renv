"""Hardening pass: paper identity, citation hygiene, bib import, discover fields.

Everything here came out of a real agent-driven corpus build (45 papers): the
library-filename/paper-key split, mis-anchored citations surviving --write,
orphan citation rows with no removal path, a .bib cold-start with no import,
and exact-title discover queries drowning in arXiv's OR-matched `all:` search.
Network is injected (`get=`), so these run offline.
"""

from __future__ import annotations

import json

import pytest

from renv.mcp_server import handle
from renv.papers import ingest
from renv.research import claim, db

ARXIV_ATOM = (
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
    "<title>An Open Event Camera Simulator</title>"
    "<published>2018-10-01T00:00:00Z</published>"
    "<summary>Adaptive sampling.</summary>"
    "<author><name>Henri Rebecq</name></author>"
    "</entry></feed>"
).encode()

EMPTY_ATOM = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'.encode()

CROSSREF_JSON = json.dumps({"message": {
    "title": ["JSTASR: Snow Removal"],
    "author": [{"given": "Wei-Ting", "family": "Chen"}],
    "published": {"date-parts": [[2020]]},
    "container-title": ["ECCV"], "DOI": "10.1007/xyz", "URL": "https://doi.org/10.1007/xyz",
}}).encode()


class _Cit:
    """Minimal Citation stand-in (mirrors test_ingest_kb)."""
    def __init__(self, source_id="rebecq2018_esim", support="partial"):
        self.source_id = source_id; self.claim = "ESIM couples renderer and simulator"
        self.start, self.end = 10, 60; self.quote = "It tightly couples…"
        self.prefix = self.suffix = ""; self.support = support; self.support_score = 0.4


# --- identity: the landed file is always named after the key -----------------
def test_file_ingest_names_library_file_after_key(tmp_path):
    con = db.connect(tmp_path)
    src = tmp_path / "Report.pdf"; src.write_bytes(b"%PDF-1.4 fake")
    res = ingest.add(con, tmp_path, str(src), key="winking2026_thesis")
    assert (tmp_path / "library" / "winking2026_thesis.pdf").exists()
    assert not (tmp_path / "library" / "Report.pdf").exists()
    assert res["paper"]["key"] == "winking2026_thesis" and res["has_text"]


def test_file_ingest_attach_preserves_existing_metadata(tmp_path):
    """DOI-first then PDF-attach must not clobber Crossref metadata with a stub."""
    con = db.connect(tmp_path)
    ingest.add(con, tmp_path, "10.1007/xyz", get=lambda url, **k: CROSSREF_JSON)
    key = ingest.list_papers(con)[0]["key"]
    src = tmp_path / "downloaded.pdf"; src.write_bytes(b"%PDF-1.4 fake")
    res = ingest.add(con, tmp_path, str(src), key=key)
    assert res["attached"] is True
    p = ingest.list_papers(con)[0]
    assert p["title"] == "JSTASR: Snow Removal" and p["year"] == 2020
    assert (tmp_path / "library" / f"{key}.pdf").exists()


def test_doi_only_ingest_reports_no_text(tmp_path):
    con = db.connect(tmp_path)
    res = ingest.add(con, tmp_path, "10.1007/xyz", get=lambda url, **k: CROSSREF_JSON)
    assert res["has_text"] is False and res["landed"] is None


def test_meta_override_fills_local_file_gaps(tmp_path):
    con = db.connect(tmp_path)
    src = tmp_path / "scan.pdf"; src.write_bytes(b"%PDF-1.4 fake")
    res = ingest.add(con, tmp_path, str(src), key="narasimhan2002_vision",
                     meta_override={"title": "Vision and the Atmosphere",
                                    "authors": ["S. Narasimhan", "S. Nayar"], "year": 2002})
    assert res["paper"]["title"] == "Vision and the Atmosphere"
    assert res["paper"]["year"] == 2002


# --- rename_source repairs a pre-existing split ------------------------------
def test_rename_source_repoints_citations(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "Report.pdf").write_bytes(b"%PDF-1.4 fake")
    ingest.add_paper(con, {"title": "Thesis", "authors": ["J W"], "year": 2026},
                     key="winking2026_thesis")
    row = ingest.record_citation(con, "p", _Cit(source_id="Report"))
    assert row["paper_id"] is None  # the split
    res = ingest.rename_source(con, tmp_path, "Report", "winking2026_thesis")
    assert res["reindex"] and res["projects"] == ["p"]
    assert (tmp_path / "library" / "winking2026_thesis.pdf").exists()
    fixed = con.execute("SELECT * FROM citation WHERE id=?", (row["id"],)).fetchone()
    assert fixed["source_id"] == "winking2026_thesis" and fixed["paper_id"] is not None
    with pytest.raises(KeyError):
        ingest.rename_source(con, tmp_path, "nope", "winking2026_thesis")


# --- remove_citation: tombstone + guard + force-retract ----------------------
def test_remove_citation_tombstones_not_deletes(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    row = ingest.record_citation(con, "p", _Cit())
    res = ingest.remove_citation(con, row["id"], reason="wrong paper")
    assert res["project"] == "p" and res["retracted_evidence"] == []
    # the row survives as history but leaves every live view
    kept = con.execute("SELECT * FROM citation WHERE id=?", (row["id"],)).fetchone()
    assert kept["retracted"] and kept["retract_reason"] == "wrong paper"
    assert ingest.citations_for_project(con, "p") == []
    assert len(ingest.citations_for_project(con, "p", live_only=False)) == 1
    out = ingest.regenerate_sidecar(con, "p", tmp_path / "projects" / "p")
    assert json.loads(out.read_text()) == []
    with pytest.raises(ValueError):  # already retracted
        ingest.remove_citation(con, row["id"])
    with pytest.raises(ValueError):  # a retracted citation cannot back a claim
        c = claim.add_claim(con, "p", "x")
        claim.link_evidence(con, c["id"], citation_id=row["id"])


def test_remove_citation_refuses_live_evidence_then_force(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    row = ingest.record_citation(con, "p", _Cit())
    c = claim.add_claim(con, "p", "renderer coupling exists")
    claim.link_evidence(con, c["id"], citation_id=row["id"], stance="supports")
    assert claim.get_claim(con, c["id"])["status"] == "supported"
    with pytest.raises(ValueError):
        ingest.remove_citation(con, row["id"])
    res = ingest.remove_citation(con, row["id"], force=True)
    assert res["retracted_evidence"] == [c["id"]]
    after = claim.get_claim(con, c["id"])
    assert after["status"] == "open"  # re-derived from live evidence only
    assert after["evidence"][0]["retracted"] is not None  # history kept, not cascaded away


# --- discover: title-phrase first, all: fallback -----------------------------
def test_search_arxiv_title_first_then_fallback():
    urls = []
    def fake_get(url, **k):
        urls.append(url)
        return EMPTY_ATOM if "ti%3A" in url else ARXIV_ATOM
    hits = ingest.search_arxiv("Snow removal in video", get=fake_get)
    assert len(urls) == 2 and "ti%3A" in urls[0] and "all%3A" in urls[1]
    assert hits and hits[0]["title"] == "An Open Event Camera Simulator"


def test_search_arxiv_title_hit_skips_fallback():
    urls = []
    def fake_get(url, **k):
        urls.append(url)
        return ARXIV_ATOM
    assert ingest.search_arxiv("event camera simulator", get=fake_get)
    assert len(urls) == 1 and "ti%3A" in urls[0]


# --- bibtex import -----------------------------------------------------------
BIB = r"""
% a comment line
@article{muglikar2025event,
  title   = {Event-Based De-Snowing for Autonomous Driving},
  author  = {Muglikar, Manasi},
  journal = {arXiv preprint arXiv:2507.20901},
  year    = {2025}
}
@inproceedings{chen2020srrs,
  title     = {JSTASR: Joint Size and Transparency-Aware Snow Removal},
  author    = {Chen, Wei-Ting},
  booktitle = {ECCV},
  doi       = {10.1007/xyz},
  year      = {2020}
}
@article{locatelli1974fall,
  title   = {Fall speeds and masses of solid precipitation particles},
  author  = {Locatelli, John D},
  journal = {Journal of Geophysical Research},
  year    = {1974}
}
"""


def test_parse_bibtex_entries_and_fields():
    entries = ingest.parse_bibtex(BIB)
    assert [e["bibkey"] for e in entries] == \
        ["muglikar2025event", "chen2020srrs", "locatelli1974fall"]
    assert entries[0]["fields"]["journal"] == "arXiv preprint arXiv:2507.20901"
    assert entries[1]["fields"]["doi"] == "10.1007/xyz"


def test_resolve_bib_entry_arxiv_doi_none():
    e = ingest.parse_bibtex(BIB)
    assert ingest.resolve_bib_entry(e[0]["fields"]) == ("arxiv", "2507.20901")
    assert ingest.resolve_bib_entry(e[1]["fields"]) == ("doi", "10.1007/xyz")
    assert ingest.resolve_bib_entry(e[2]["fields"]) is None


def test_add_bib_ingests_resolvable_entries(tmp_path):
    con = db.connect(tmp_path)
    bib = tmp_path / "refs.bib"; bib.write_text(BIB)
    def fake_get(url, **k):
        return CROSSREF_JSON if "crossref" in url else ARXIV_ATOM
    res = ingest.add_bib(con, tmp_path, bib, get=fake_get)
    assert {a["bibkey"] for a in res["added"]} == {"muglikar2025event", "chen2020srrs"}
    assert res["unresolved"][0]["bibkey"] == "locatelli1974fall"
    keys = {p["key"] for p in ingest.list_papers(con)}
    assert {"muglikar2025event", "chen2020srrs"} <= keys  # bib keys, not derived keys


# --- retriever --source pin --------------------------------------------------
def test_retriever_source_filter():
    from renv.corpus.retrieve import Retriever

    class _Rec:
        def __init__(self, source_id, text):
            self.source_id = source_id; self.text = text
            self.vector = {w: 1.0 for w in text.split()}
            self.chunk_id = 0; self.start = 0; self.end = len(text); self.page = 1

    class _Index:
        records = [_Rec("paper_a", "snow simulation events"),
                   _Rec("paper_b", "snow simulation events blender")]

    class _Emb:
        def encode(self, texts):
            return [{w: 1.0 for w in t.split()} for t in texts]

    r = Retriever(_Index(), _Emb(), verifier=None)
    top = r.search("snow simulation events blender", top_k=5, verify=False)
    assert top[0].record.source_id == "paper_b"
    pinned = r.search("snow simulation events blender", top_k=5, verify=False,
                      source_id="paper_a")
    assert [c.record.source_id for c in pinned] == ["paper_a"]
    assert r.search("anything", top_k=5, verify=False, source_id="missing") == []


# --- MCP parity --------------------------------------------------------------
def _call(root, name, args):
    resp = handle(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": name, "arguments": args}})
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_mcp_list_and_remove_citation(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    row = ingest.record_citation(con, "p", _Cit())
    con.close()
    rows = _call(tmp_path, "list_citations", {"project": "p"})
    assert rows[0]["id"] == row["id"] and rows[0]["live_claim_links"] == 0
    res = _call(tmp_path, "remove_citation", {"citation_id": row["id"]})
    assert res["id"] == row["id"]
    rows = _call(tmp_path, "list_citations", {"project": "p"})
    assert rows[0]["retracted"]  # tombstoned, still listed as history
