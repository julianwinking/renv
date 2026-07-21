"""W3C Web Annotation selectors — the version-robust citation anchor.

We store a citation as the *quoted text* plus a little context, following the
W3C Web Annotation Data Model (Recommendation, 2017-02-23):

  - TextQuoteSelector : exact + prefix + suffix   (§4.2.4) -- durable, self-verifying
  - TextPositionSelector : start + end            (§4.2.5) -- fast, but offsets drift

Resolution strategy (mirrors Hypothes.is fuzzy anchoring):
  1. trust the position offsets if the text there still matches `exact`;
  2. else relocate by fuzzy-matching prefix+exact+suffix (rapidfuzz if present,
     stdlib difflib otherwise).

Because the anchor carries the quoted text, a citation made against version v1 of
a paper can still be resolved against v2 even when every offset has moved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

try:  # optional, MIT — much better fuzzy alignment with offsets
    from rapidfuzz import fuzz as _rf_fuzz
    _HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - fallback path
    _HAVE_RAPIDFUZZ = False
    import difflib


@dataclass
class TextQuoteSelector:
    exact: str
    prefix: str = ""
    suffix: str = ""
    type: str = "TextQuoteSelector"


@dataclass
class TextPositionSelector:
    start: int
    end: int
    type: str = "TextPositionSelector"


@dataclass
class Anchor:
    """A W3C-style anchor pairing the durable quote with a position hint."""
    quote: TextQuoteSelector
    position: TextPositionSelector

    def to_dict(self) -> dict:
        return {"quote": asdict(self.quote), "position": asdict(self.position)}

    @classmethod
    def from_dict(cls, d: dict) -> "Anchor":
        q = d["quote"]
        p = d["position"]
        return cls(
            quote=TextQuoteSelector(exact=q["exact"], prefix=q.get("prefix", ""),
                                    suffix=q.get("suffix", "")),
            position=TextPositionSelector(start=p["start"], end=p["end"]),
        )


def build_anchor(text: str, start: int, end: int, context: int = 32) -> Anchor:
    """Build an anchor for text[start:end] with surrounding context."""
    exact = text[start:end]
    prefix = text[max(0, start - context):start]
    suffix = text[end:end + context]
    return Anchor(
        quote=TextQuoteSelector(exact=exact, prefix=prefix, suffix=suffix),
        position=TextPositionSelector(start=start, end=end),
    )


@dataclass
class Resolution:
    start: int
    end: int
    score: float          # 1.0 == exact; <1.0 == fuzzy confidence
    method: str           # "position" | "fuzzy" | "exact-search"


def _fuzzy_locate(text: str, needle: str) -> tuple[int, int, float]:
    """Best fuzzy substring of `text` matching `needle` -> (start, end, score 0..1)."""
    if not needle:
        return (0, 0, 0.0)
    if _HAVE_RAPIDFUZZ:
        al = _rf_fuzz.partial_ratio_alignment(needle, text)
        if al is None:
            return (0, 0, 0.0)
        return (al.dest_start, al.dest_end, al.score / 100.0)
    # stdlib fallback: slide a window sized like the needle, score by ratio.
    n = len(needle)
    best = (0, 0, 0.0)
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(needle)
    step = max(1, n // 8)
    for i in range(0, max(1, len(text) - n + 1), step):
        window = text[i:i + n]
        sm.set_seq1(window)
        r = sm.ratio()
        if r > best[2]:
            best = (i, i + n, r)
    return best


def resolve(text: str, anchor: Anchor, accept: float = 0.7) -> Resolution | None:
    """Resolve an anchor against (possibly newer) `text`.

    Returns the located span or None if confidence is below `accept`.
    """
    exact = anchor.quote.exact
    s, e = anchor.position.start, anchor.position.end

    # 1. position hint still valid?
    if 0 <= s <= e <= len(text) and text[s:e] == exact:
        return Resolution(s, e, 1.0, "position")

    # 2. exact substring search anchored by context when available
    target = anchor.quote.prefix + exact + anchor.quote.suffix
    idx = text.find(target)
    if idx != -1:
        cs = idx + len(anchor.quote.prefix)
        return Resolution(cs, cs + len(exact), 1.0, "exact-search")
    idx = text.find(exact)
    if idx != -1:
        return Resolution(idx, idx + len(exact), 1.0, "exact-search")

    # 3. fuzzy relocation using context to disambiguate
    cs, ce, score = _fuzzy_locate(text, target if (anchor.quote.prefix or anchor.quote.suffix) else exact)
    if score >= accept:
        # trim back to the exact span inside the matched context window
        window = text[cs:ce]
        inner_s, inner_e, _ = _fuzzy_locate(window, exact)
        return Resolution(cs + inner_s, cs + inner_e, score, "fuzzy")
    return None
