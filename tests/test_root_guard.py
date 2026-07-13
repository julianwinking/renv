"""A new .research store must never be created inside an existing env.

The failure mode this pins down: a command run from a subdirectory (cockpit/,
projects/x/) would silently create a fresh empty DB there and the cockpit
would show "no projects". connect() now refuses at the deepest layer.
"""

from __future__ import annotations

import pytest

from reref import db


def test_refuses_new_store_inside_existing_env(tmp_path):
    db.connect(tmp_path).close()                     # the real env root
    sub = tmp_path / "cockpit"
    sub.mkdir()
    with pytest.raises(RuntimeError, match="env already exists"):
        db.connect(sub)
    deep = tmp_path / "projects" / "p" / "src"
    deep.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="env already exists"):
        db.connect(deep)


def test_existing_stores_and_fresh_roots_still_work(tmp_path):
    a = tmp_path / "env-a"
    a.mkdir()
    db.connect(a).close()                            # fresh root: fine
    db.connect(a).close()                            # reopening the same root: fine
    b = tmp_path / "env-b"                           # sibling env: fine
    b.mkdir()
    db.connect(b).close()
