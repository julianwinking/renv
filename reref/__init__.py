"""recursive-referencing: local, span-anchored, verified citations.

Pipeline:
    library/*.pdf  --parse-->  text + char offsets
                   --chunk-->  passages (sentence/paragraph) with offsets
                   --embed-->  vectors  --> index (+ lockfile manifest)

At authoring time, for a claim written in text/:
    claim --retrieve--> candidate passages
          --anchor-->   W3C TextQuote + TextPosition selectors (version-robust)
          --verify-->   does the span actually support the claim?
          --cite-->     \\spancite{...} macro + citations.json sidecar

The citation points at the *quoted span text*, not at a chunk/vector id, so it is
self-verifying and survives re-indexing and new document versions.
"""

__version__ = "0.1.0"
