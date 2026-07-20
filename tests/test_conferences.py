"""The conference-deadlines feed: fetch, cache, offline fallback."""

from __future__ import annotations

import json

import pytest

from renv import conferences

SAMPLE = json.dumps([{"title": "NeurIPS", "year": 2026, "id": "neurips26",
                      "deadline": "2026-05-15 20:00:00", "sub": ["ML"]}])


def test_fetch_caches_and_serves_offline(tmp_path):
    calls = []

    def fake_get(url):
        calls.append(url)
        return SAMPLE

    data = conferences.fetch(tmp_path, get=fake_get)
    assert data[0]["title"] == "NeurIPS" and len(calls) == 1
    # fresh cache wins — no second network call even with a working getter
    data = conferences.fetch(tmp_path, get=fake_get)
    assert len(calls) == 1
    # expired cache + dead network → stale cache beats nothing
    def dead_get(url):
        raise OSError("offline")
    data = conferences.fetch(tmp_path, ttl=0, get=dead_get)
    assert data[0]["id"] == "neurips26"


def test_fetch_offline_without_cache_raises(tmp_path):
    def dead_get(url):
        raise OSError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        conferences.fetch(tmp_path, get=dead_get)


def test_bad_feed_shape_rejected_not_cached(tmp_path):
    with pytest.raises(RuntimeError):
        conferences.fetch(tmp_path, get=lambda u: '{"not": "a list"}')
    assert not (tmp_path / ".research" / "cache" / "conferences.json").exists()
