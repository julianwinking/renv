"""Reference intelligence: parse a paper's References section, match entries to
the corpus, record human relevance verdicts, and run the reader inbox."""

from __future__ import annotations

import pytest

from renv.papers import bibliography as bib
from renv.papers import ingest
from renv.research import db

ARXIV_ATOM = (
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
    "<title>ESIM: an Open Event Camera Simulator</title>"
    "<published>2018-10-01T00:00:00Z</published>"
    "<summary>sim</summary>"
    "<author><name>Henri Rebecq</name></author>"
    "</entry></feed>"
).encode()

PAPER = """Intro: event simulation [1] beats interpolation [2, 3]. Ranges too [1-3].
Equation refs like [12] must not leak. Deep nets [4] help.

References

[1] H. Rebecq, D. Gehrig. ESIM: an Open Event Camera Simulator. CoRL, 2018.
arXiv:1810.03769.
[2] Y. Hu, S. Liu, T. Delbruck. v2e: From Video Frames to Realistic DVS Events.
CVPRW 2021. doi:10.1109/CVPRW53098.2021.00149
[3] S. Lin, Y. Ma. DVS-Voltmeter: Stochastic Process-based Event Simulator for
Dynamic Vision Sensors. ECCV 2022.
[4] A. Nobody. An Utterly Unmatched Reference Nobody Ingested. Journal of
Missing Papers, 1999.
"""


def _env(tmp_path):
    con = db.connect(tmp_path)
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "citing2026_paper.txt").write_text(PAPER)
    ingest.add_paper(con, {"title": "Citing Paper", "authors": ["C"], "year": 2026},
                     key="citing2026_paper")
    return con


# --- parsing -----------------------------------------------------------------
def test_split_reference_entries_numeric():
    sec, entries = bib.split_reference_entries(PAPER)
    assert sec is not None and [e["num"] for e in entries] == [1, 2, 3, 4]
    assert "ESIM" in entries[0]["raw"] and "Voltmeter" in entries[2]["raw"]
    assert PAPER[entries[1]["start"]:entries[1]["end"]].strip() == entries[1]["raw"]


def test_find_markers_expands_and_filters():
    sec, entries = bib.split_reference_entries(PAPER)
    ms = bib.find_markers(PAPER, {e["num"] for e in entries}, until=sec)
    got = [m["nums"] for m in ms]
    assert [1] in got and [2, 3] in got and [1, 2, 3] in got and [4] in got
    assert not any(12 in nums for nums in got)  # unknown number dropped


def test_no_references_section_is_graceful():
    assert bib.split_reference_entries("short text, no refs") == (None, [])


def test_lncs_dotted_reference_list():
    """Springer/LNCS: in-text [N], but the LIST numbers entries as 'N.'."""
    t = ("We compare against supervised [1,2] and UDA methods [3].\n\nReferences\n\n"
         "1. Alonso, I., Murillo A.: EV-SegNet. In: CVPRW (2019)\n"
         "2. Binas, J., et al.: DDD17: end-to-end DAVIS driving dataset (2017)\n"
         "3. Chen, L.C., et al.: Rethinking atrous convolution. arXiv:1706.05587\n")
    sec, entries = bib.split_reference_entries(t)
    assert [e["num"] for e in entries] == [1, 2, 3]
    assert "EV-SegNet" in entries[0]["raw"] and "DDD17" in entries[1]["raw"]


def test_entries_before_heading_column_scramble():
    """pdfminer two-column output can emit entries BEFORE the heading."""
    t = ("[1] A. Author. First paper. CVPR 2020.\n"
         "[2] B. Author. Second paper. ECCV 2021.\n"
         "[3] C. Author. Third paper. ICCV 2022.\n"
         "[4] D. Author. Fourth paper. CVPR 2023.\n\nReferences\n\npage 12\n")
    sec, entries = bib.split_reference_entries(t)
    assert [e["num"] for e in entries] == [1, 2, 3, 4]
    assert "First paper" in entries[0]["raw"]


def test_body_citation_sequence_is_not_a_reference_list():
    """A paper citing [1], [2], [3] pages apart must not parse as a list."""
    filler = "x" * 3000
    t = f"Intro [1] {filler} middle [2] {filler} end [3] {filler}"
    sec, entries = bib.split_reference_entries(t)
    assert entries == []


# --- build + matching --------------------------------------------------------
def test_build_references_matches_by_arxiv_doi_title(tmp_path):
    con = _env(tmp_path)
    ingest.add_paper(con, {"title": "ESIM: an Open Event Camera Simulator",
                           "authors": ["Rebecq"], "year": 2018, "arxiv": "1810.03769"},
                     key="rebecq2018_esim")
    ingest.add_paper(con, {"title": "v2e paper", "authors": ["Hu"], "year": 2021,
                           "doi": "10.1109/CVPRW53098.2021.00149"}, key="hu2021_v2e")
    ingest.add_paper(con, {"title": "DVS-Voltmeter: Stochastic Process-based Event "
                           "Simulator for Dynamic Vision Sensors",
                           "authors": ["Lin"], "year": 2022}, key="lin2022_dvsvoltmeter")
    res = bib.build_references(con, tmp_path, "citing2026_paper")
    assert res["style"] == "numeric" and res["count"] == 4
    refs = bib.list_references(con, "citing2026_paper")
    by = {r["num"]: r for r in refs}
    assert by[1]["status"] == "library" and by[1]["matched_key"] == "rebecq2018_esim"
    assert by[2]["status"] == "library"            # DOI match
    assert by[3]["status"] == "library"            # title-token match
    assert by[4]["status"] == "unknown" and by[4]["matched_paper_id"] is None


def test_markers_carry_worst_status(tmp_path):
    con = _env(tmp_path)
    bib.build_references(con, tmp_path, "citing2026_paper")
    out = bib.reference_markers(con, tmp_path, "citing2026_paper")
    assert all(m["status"] == "unknown" for m in out["markers"])  # nothing matched yet
    assert out["section_start"] is not None
    assert set(out["statuses"]) == {1, 2, 3, 4}


# --- verdicts ----------------------------------------------------------------
def test_mark_reference_requires_comment_and_survives_rebuild(tmp_path):
    con = _env(tmp_path)
    bib.build_references(con, tmp_path, "citing2026_paper")
    ref4 = [r for r in bib.list_references(con, "citing2026_paper") if r["num"] == 4][0]
    with pytest.raises(ValueError):
        bib.mark_reference(con, ref4["id"], "not_relevant")          # no comment
    with pytest.raises(ValueError):
        bib.mark_reference(con, ref4["id"], "somestatus", "x")       # bad verdict
    r = bib.mark_reference(con, ref4["id"], "not_relevant", "1999, pre-DVS, off-topic")
    assert r["status"] == "not_relevant"
    bib.build_references(con, tmp_path, "citing2026_paper")          # rebuild
    again = [r for r in bib.list_references(con, "citing2026_paper") if r["num"] == 4][0]
    assert again["verdict"] == "not_relevant"
    assert again["verdict_comment"] == "1999, pre-DVS, off-topic"
    cleared = bib.mark_reference(con, again["id"], None)
    assert cleared["status"] == "unknown" and cleared["verdict_comment"] is None


# --- add-to-library + inbox --------------------------------------------------
def test_add_reference_ingests_and_inboxes(tmp_path):
    con = _env(tmp_path)
    bib.build_references(con, tmp_path, "citing2026_paper")
    refs = {r["num"]: r for r in bib.list_references(con, "citing2026_paper")}
    res = bib.add_reference(con, tmp_path, refs[1]["id"], download=False,
                            get=lambda url, **k: ARXIV_ATOM)
    assert res["paper"]["inbox"] == 1
    assert bib.list_references(con, "citing2026_paper")[0]["status"] == "library"
    keys = [p["key"] for p in bib.inbox(con)]
    assert res["paper"]["key"] in keys
    bib.mark_read(con, res["paper"]["key"])
    assert bib.inbox(con) == []
    with pytest.raises(ValueError):   # already in library
        bib.add_reference(con, tmp_path, refs[1]["id"], get=lambda url, **k: ARXIV_ATOM)
    with pytest.raises(ValueError):   # no identifier on [4]
        bib.add_reference(con, tmp_path, refs[4]["id"], get=lambda url, **k: ARXIV_ATOM)


def test_build_references_needs_text(tmp_path):
    con = db.connect(tmp_path)
    ingest.add_paper(con, {"title": "Ghost", "authors": [], "year": None}, key="ghost")
    with pytest.raises(ValueError):
        bib.build_references(con, tmp_path, "ghost")
    with pytest.raises(KeyError):
        bib.build_references(con, tmp_path, "nope")
