"""Literature discovery — arXiv keyword search (offline via injected get)."""

from __future__ import annotations

from renv import db, ingest

FEED = (
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<entry><id>http://arxiv.org/abs/2305.14627v1</id>'
    '<title>Enabling LLMs to Generate Text with Citations</title>'
    '<published>2023-05-23T00:00:00Z</published><summary>ALCE.</summary>'
    '<author><name>Tianyu Gao</name></author></entry>'
    '<entry><id>http://arxiv.org/abs/2409.02897v2</id>'
    '<title>LongCite</title><published>2024-09-01T00:00:00Z</published>'
    '<summary>sentence-level cites.</summary>'
    '<author><name>Jiajie Zhang</name></author></entry>'
    '</feed>'
).encode()


def test_search_arxiv_returns_multiple(tmp_path):
    res = ingest.search_arxiv("citation", get=lambda url, **k: FEED)
    assert len(res) == 2
    assert res[0]["arxiv"] == "2305.14627v1" and res[0]["year"] == 2023
    assert res[1]["title"] == "LongCite"


def test_discover_then_add(tmp_path):
    con = db.connect(tmp_path)
    res = ingest.search_arxiv("citation", get=lambda url, **k: FEED)
    paper = ingest.add_paper(con, res[0])
    assert paper["key"].startswith("gao2023")
    assert ingest.list_papers(con)[0]["arxiv"] == "2305.14627v1"
