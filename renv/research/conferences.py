"""Conference deadlines (Tools) — the ai-deadlines feed, cached locally.

Fetched from mlciv.com/ai-deadlines (a maintained fork of the paperswithcode
ai-deadlines list) and cached for 24h under .research/cache/, so the page
works offline and never hammers the source. This is telescope data, not
research state: nothing lands in the store unless the user explicitly adopts
a deadline into the plan (which creates a normal plan_item).
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

URL = "https://mlciv.com/ai-deadlines/conferences.json"
TTL = 86400  # a day — deadlines don't move faster than that


def _default_get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode("utf-8")


def fetch(root=".", *, ttl: int = TTL, get=None) -> list[dict]:
    """The conference list; fresh cache wins, then network, then stale cache."""
    cache = Path(root) / ".research" / "cache" / "conferences.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
        return json.loads(cache.read_text())
    try:
        raw = (get or _default_get)(URL)
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("unexpected feed shape")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(raw)
        return data
    except Exception as exc:
        if cache.exists():
            return json.loads(cache.read_text())   # stale beats nothing
        raise RuntimeError(
            f"could not fetch the conference list ({exc}) — offline? try again later")
