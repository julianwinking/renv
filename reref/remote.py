"""The remote registry — named compute/storage locations (your clusters).

A remote references an existing ssh alias (``ssh snaga`` keeps working exactly
as configured in ~/.ssh/config — we never duplicate hosts, users, or keys) and
carries a ``data_root``: the default place experiment data lives there. That
makes locators shorthand: ``snaga:runs/exp42`` expands to
``snaga:/<data_root>/runs/exp42`` wherever a run or dataset records where it
lives. ``host`` NULL means this machine (a named local data root).
"""

from __future__ import annotations

import re
import sqlite3

from .db import now, row_to_dict

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def add_remote(con: sqlite3.Connection, name: str, *, host: str | None = None,
               data_root: str | None = None, description: str | None = None) -> dict:
    """Register (or update) a named remote. ``host`` is the ssh alias."""
    if not _NAME.match(name):
        raise ValueError("remote name must be short lowercase [a-z0-9_-]")
    con.execute(
        "INSERT INTO remote (name, host, data_root, description, created) "
        "VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET host=excluded.host, "
        "data_root=excluded.data_root, description=excluded.description",
        (name, host or name, data_root, description, now()))
    con.commit()
    return get_remote(con, name)


def get_remote(con: sqlite3.Connection, name: str) -> dict | None:
    return row_to_dict(con.execute(
        "SELECT * FROM remote WHERE name=?", (name,)).fetchone())


def list_remotes(con: sqlite3.Connection) -> list[dict]:
    return [row_to_dict(r) for r in con.execute("SELECT * FROM remote ORDER BY name")]


def delete_remote(con: sqlite3.Connection, name: str) -> None:
    if not get_remote(con, name):
        raise KeyError(f"no remote {name!r}")
    con.execute("DELETE FROM remote WHERE name=?", (name,))
    con.commit()


def expand_locator(con: sqlite3.Connection, locator: str | None) -> str | None:
    """Expand ``name:relative/path`` against the remote's data_root.

    ``snaga:runs/exp42`` → ``snaga:/scratch/…/runs/exp42``. Absolute paths,
    full URIs (ssh://…), and unknown prefixes pass through unchanged — the
    registry adds convenience, never a gate.
    """
    if not locator or locator.startswith(("/", "ssh://", "http://", "https://")):
        return locator
    name, sep, path = locator.partition(":")
    if not sep:
        return locator
    r = get_remote(con, name)
    if not r:
        return locator
    if path and not path.startswith("/") and r["data_root"]:
        path = r["data_root"].rstrip("/") + "/" + path
    return f"{name}:{path}" if path else f"{name}:{r['data_root'] or ''}"
