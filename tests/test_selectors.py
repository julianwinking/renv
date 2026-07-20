"""The genuinely critical, dependency-free core: anchors must survive edits.

Run: python -m pytest tests/  (or python tests/test_selectors.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renv.selectors import build_anchor, resolve  # noqa: E402

V1 = (
    "Large language models can hallucinate references. "
    "Span-level citation anchors the exact passage in the source. "
    "This makes the claim self-verifying across versions."
)


def test_exact_roundtrip():
    start = V1.index("Span-level")
    end = V1.index("source.") + len("source.")
    a = build_anchor(V1, start, end)
    r = resolve(V1, a)
    assert r is not None and r.method == "position" and r.score == 1.0
    assert V1[r.start:r.end] == a.quote.exact


def test_resolves_after_insertion_shifts_offsets():
    start = V1.index("Span-level")
    end = V1.index("source.") + len("source.")
    a = build_anchor(V1, start, end)
    # a newer version inserts a sentence up front -> all offsets move
    v2 = "ABSTRACT. " + V1.replace("hallucinate", "sometimes hallucinate")
    r = resolve(v2, a)
    assert r is not None, "anchor should relocate in the edited version"
    assert "Span-level citation anchors the exact passage" in v2[r.start:r.end]


def test_rejects_absent_quote():
    a = build_anchor(V1, 0, 10)
    a.quote.exact = "completely unrelated text not present anywhere here"
    a.quote.prefix = a.quote.suffix = ""
    a.position.start, a.position.end = 9999, 99999
    assert resolve("a totally different document about cats", a, accept=0.7) is None


if __name__ == "__main__":
    test_exact_roundtrip()
    test_resolves_after_insertion_shifts_offsets()
    test_rejects_absent_quote()
    print("ok: all selector tests passed")
