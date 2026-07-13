"""Datasets as first-class, versioned, hashed records.

Evaluation is not an afterthought: a run pins the exact dataset (slug + version +
content hash) it was measured on, so a metric is never ambiguous about *what* it
measured. Registering a dataset by path records its sha256 for provenance; the
bytes themselves stay on disk.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import sha256_file
from .db import now, row_to_dict


def register_dataset(
    con: sqlite3.Connection,
    slug: str,
    *,
    version: str = "1",
    path: str | None = None,
    description: str | None = None,
    location: str | None = None,
    sha256: str | None = None,
) -> dict:
    """Register (or return) dataset ``slug@version``.

    Local data: pass ``path`` — hashed here, and recorded as the location.
    Cluster-resident data: pass ``location`` (e.g. ``ssh://cluster/data/x``)
    plus ``sha256`` computed remotely (``shasum -a 256`` on the cluster), so
    hash-pinning survives without the bytes ever touching this machine.
    """
    sha = sha256 or (sha256_file(Path(path)) if path else None)
    location = location or path
    if location:
        from .remote import expand_locator
        location = expand_locator(con, location)
    row = con.execute(
        "SELECT * FROM dataset WHERE slug=? AND version=?", (slug, version)
    ).fetchone()
    if row:
        # a fixed (slug, version) must mean fixed bytes — reject silent content drift
        if sha and row["sha256"] and sha != row["sha256"]:
            raise ValueError(
                f"dataset {slug}@{version} already registered with a different hash; "
                "bump the version instead of re-pointing it at new bytes")
        return row_to_dict(row)
    cur = con.execute(
        "INSERT INTO dataset (slug, version, sha256, description, created, location) "
        "VALUES (?,?,?,?,?,?)",
        (slug, version, sha, description, now(), location),
    )
    con.commit()
    return row_to_dict(
        con.execute("SELECT * FROM dataset WHERE id=?", (cur.lastrowid,)).fetchone()
    )


def get_dataset(con: sqlite3.Connection, slug: str, version: str = "1") -> dict | None:
    return row_to_dict(
        con.execute(
            "SELECT * FROM dataset WHERE slug=? AND version=?", (slug, version)
        ).fetchone()
    )


def list_datasets(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("SELECT * FROM dataset ORDER BY slug, version").fetchall()
    return [row_to_dict(r) for r in rows]
