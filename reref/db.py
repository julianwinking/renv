"""The central store: one SQLite database = the single ground truth.

The structured state of the whole environment is relational (configs linked to
runs, runs to datasets, citations to papers), so it lives in one embedded SQLite
file under ``<root>/.research/env.db``. All three clients — the ``reref`` CLI, the
MCP server, and the web cockpit — go through this module and the domain modules on
top of it, so the schema constraints below hold no matter who writes.

Why SQLite: relational with real foreign keys, a single durable portable file, no
server daemon, full-text search available, and it is in the Python standard library
(``sqlite3``) — zero new dependency, consistent with the stdlib-first engine.

Reproducibility: a ``run`` pins the full reproduction tuple (git sha, environment
hash, corpus lock hash, config hash, dataset version, seed). The binary DB is not
the git artifact — :func:`export` writes a deterministic JSONL-per-table snapshot
that is committed for diffs.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_DIRNAME = ".research"
DB_FILENAME = "env.db"
EXPORT_DIRNAME = "export"

# Tables in dependency order — also the export order.
TABLES = [
    "project", "paper", "card", "dataset", "experiment", "config", "run",
    "metric", "artifact", "citation", "claim", "claim_evidence",
    "log_entry", "log_evidence", "note",
    "review_run", "finding", "finding_evidence", "adjudication",
]

# --- schema, versioned via PRAGMA user_version -------------------------------
# Each migration is one schema step. Append new migrations; never edit old ones.
_SCHEMA_V1 = """
CREATE TABLE project (
    id      INTEGER PRIMARY KEY,
    slug    TEXT NOT NULL UNIQUE,
    title   TEXT,
    status  TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    created TEXT NOT NULL
);

CREATE TABLE paper (
    id      INTEGER PRIMARY KEY,
    key     TEXT NOT NULL UNIQUE,
    title   TEXT,
    authors_json TEXT,
    year    INTEGER,
    venue   TEXT,
    doi     TEXT,
    arxiv   TEXT,
    url     TEXT,
    sha256  TEXT,
    tags_json TEXT,
    added   TEXT NOT NULL
);

CREATE TABLE card (
    id      INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    field   TEXT NOT NULL,
    text    TEXT,
    anchor_json TEXT,
    extracted_by TEXT,
    model   TEXT,
    generated TEXT
);

CREATE TABLE dataset (
    id      INTEGER PRIMARY KEY,
    slug    TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1',
    sha256  TEXT,
    description TEXT,
    created TEXT NOT NULL,
    UNIQUE(slug, version)
);

CREATE TABLE experiment (
    id        INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES experiment(id) ON DELETE SET NULL,
    slug      TEXT NOT NULL,
    title     TEXT,
    hypothesis TEXT,
    status    TEXT NOT NULL DEFAULT 'planned'
              CHECK(status IN ('planned','running','done','abandoned')),
    created   TEXT NOT NULL,
    completed TEXT,
    UNIQUE(project_id, slug)
);

CREATE TABLE config (
    id      INTEGER PRIMARY KEY,
    hash    TEXT NOT NULL UNIQUE,
    params_json TEXT NOT NULL
);

CREATE TABLE run (
    id        INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiment(id) ON DELETE CASCADE,
    config_id INTEGER REFERENCES config(id),
    dataset_id INTEGER REFERENCES dataset(id),
    git_sha   TEXT,
    env_hash  TEXT,
    corpus_lock_hash TEXT,
    seed      INTEGER,
    status    TEXT NOT NULL DEFAULT 'running'
              CHECK(status IN ('running','done','failed')),
    started   TEXT NOT NULL,
    finished  TEXT
);

CREATE TABLE metric (
    id      INTEGER PRIMARY KEY,
    run_id  INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    name    TEXT NOT NULL,
    value   REAL,
    split   TEXT
);

CREATE TABLE artifact (
    id      INTEGER PRIMARY KEY,
    run_id  INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    path    TEXT NOT NULL,
    sha256  TEXT,
    kind    TEXT
);

CREATE TABLE citation (
    id        INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    paper_id  INTEGER REFERENCES paper(id),
    claim_text TEXT,
    src_start INTEGER,
    src_end   INTEGER,
    quote     TEXT,
    prefix    TEXT,
    suffix    TEXT,
    support   TEXT,
    support_score REAL,
    manuscript_loc TEXT,
    created   TEXT NOT NULL
);

CREATE TABLE claim (
    id        INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    text      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'assertion'
              CHECK(kind IN ('thesis','contribution','assertion')),
    manuscript_loc TEXT,
    status    TEXT NOT NULL DEFAULT 'open'
              CHECK(status IN ('open','supported','refuted')),
    created   TEXT NOT NULL
);

CREATE TABLE claim_evidence (
    id        INTEGER PRIMARY KEY,
    claim_id  INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    citation_id INTEGER REFERENCES citation(id) ON DELETE CASCADE,
    run_id    INTEGER REFERENCES run(id) ON DELETE CASCADE,
    stance    TEXT NOT NULL DEFAULT 'supports'
              CHECK(stance IN ('supports','refutes')),
    note      TEXT,
    CHECK(citation_id IS NOT NULL OR run_id IS NOT NULL)
);

CREATE TABLE log_entry (
    id        INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    experiment_id INTEGER REFERENCES experiment(id) ON DELETE SET NULL,
    type      TEXT NOT NULL
              CHECK(type IN ('decision','hypothesis','observation','result','blocker')),
    ts        TEXT NOT NULL,
    body_md   TEXT NOT NULL
);

CREATE TABLE log_evidence (
    id        INTEGER PRIMARY KEY,
    log_entry_id INTEGER NOT NULL REFERENCES log_entry(id) ON DELETE CASCADE,
    run_id    INTEGER REFERENCES run(id) ON DELETE CASCADE,
    citation_id INTEGER REFERENCES citation(id) ON DELETE CASCADE,
    CHECK(run_id IS NOT NULL OR citation_id IS NOT NULL)
);

CREATE TABLE note (
    id        INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    ts        TEXT NOT NULL,
    title     TEXT,
    body_md   TEXT NOT NULL
);

CREATE INDEX idx_experiment_project ON experiment(project_id);
CREATE INDEX idx_run_experiment ON run(experiment_id);
CREATE INDEX idx_metric_run ON metric(run_id);
CREATE INDEX idx_log_project ON log_entry(project_id);
CREATE INDEX idx_citation_paper ON citation(paper_id);
"""

# v2: review findings become persistent, branchable, adjudicable nodes. A finding
# carries the evidence it cited; an append-only adjudication trail records
# accept/reject + reasoning so a future review or agent never re-raises a settled
# finding (the dedup-by-memory that curbs repeated/hallucinated findings).
_SCHEMA_V2 = """
CREATE TABLE review_run (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    ts         TEXT NOT NULL,
    n_open     INTEGER NOT NULL DEFAULT 0,
    n_suppressed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE finding (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    review_run_id INTEGER REFERENCES review_run(id) ON DELETE SET NULL,
    fingerprint TEXT NOT NULL,          -- stable identity for dedup across reviews
    check_id    TEXT,
    section     TEXT,
    dimension   TEXT,
    severity    TEXT,
    issue       TEXT,
    location_json TEXT,                 -- the proof/reference reported with it
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open','accepted','rejected','resolved')),
    created     TEXT NOT NULL
);
CREATE INDEX idx_finding_fp ON finding(project_id, fingerprint);

CREATE TABLE finding_evidence (
    id          INTEGER PRIMARY KEY,
    finding_id  INTEGER NOT NULL REFERENCES finding(id) ON DELETE CASCADE,
    citation_id INTEGER REFERENCES citation(id) ON DELETE CASCADE,
    run_id      INTEGER REFERENCES run(id) ON DELETE CASCADE,
    claim_id    INTEGER REFERENCES claim(id) ON DELETE CASCADE,
    note        TEXT,
    CHECK(citation_id IS NOT NULL OR run_id IS NOT NULL OR claim_id IS NOT NULL)
);

CREATE TABLE adjudication (
    id          INTEGER PRIMARY KEY,
    finding_id  INTEGER NOT NULL REFERENCES finding(id) ON DELETE CASCADE,
    verdict     TEXT NOT NULL CHECK(verdict IN ('accept','reject','defer')),
    reasoning   TEXT NOT NULL,          -- required: future agents must see WHY
    by          TEXT,
    ts          TEXT NOT NULL
);
"""

# v3: honest run provenance. A run records the entrypoint it executed (+ its hash),
# whether the git tree was dirty, and a provenance grade — so a number from a fully
# pinned run is distinguishable from one whose tree was dirty or whose env/dataset
# was unpinned. (Reproducibility is provenance + grade, not a guarantee — see docs.)
_SCHEMA_V3 = """
ALTER TABLE run ADD COLUMN entrypoint TEXT;
ALTER TABLE run ADD COLUMN entrypoint_sha TEXT;
ALTER TABLE run ADD COLUMN dirty INTEGER;
ALTER TABLE run ADD COLUMN provenance TEXT;
"""

# v4: the citation table becomes the single source of truth; citations.json is
# derived from it. Store the source_id (the \spancite key) so the sidecar and the
# review's \spancite check both resolve against the table, not a separate file.
_SCHEMA_V4 = """
ALTER TABLE citation ADD COLUMN source_id TEXT;
"""

# v5: metric definitions — a registry standardizing how a metric NAME is
# rendered and compared everywhere (CLI, web, weave): display label, unit,
# direction (is bigger better?), printf-style format. Registration is optional:
# an unregistered metric still records and displays (raw), it just isn't
# standardized. `metric` rows stay the sole home of the numbers.
_SCHEMA_V5 = """
CREATE TABLE metric_def (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    label       TEXT,
    unit        TEXT,
    direction   TEXT NOT NULL DEFAULT 'maximize'
                CHECK(direction IN ('maximize','minimize','info')),
    fmt         TEXT NOT NULL DEFAULT '.3f',
    description TEXT
);
"""

# v6: log entries gain two types — 'question' (+ an `answers` self-link: a
# question stays open until a later entry answers it; status DERIVED, like
# claims) and 'feedback' (external input, e.g. an advisor) — plus a `source`
# column recording WHO wrote an entry (you / agent / "Prof. X").
# CHECK constraints can't be altered in place, so this rebuilds log_entry
# (SQLite's documented recipe; _migrate turns FKs off around the pass so the
# DROP doesn't cascade into log_evidence).
_SCHEMA_V6 = """
CREATE TABLE log_entry_v6 (
    id        INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    experiment_id INTEGER REFERENCES experiment(id) ON DELETE SET NULL,
    type      TEXT NOT NULL
              CHECK(type IN ('decision','hypothesis','observation','result',
                             'blocker','question','feedback')),
    ts        TEXT NOT NULL,
    body_md   TEXT NOT NULL,
    answers   INTEGER REFERENCES log_entry(id) ON DELETE SET NULL,
    source    TEXT
);
INSERT INTO log_entry_v6 (id, project_id, experiment_id, type, ts, body_md)
    SELECT id, project_id, experiment_id, type, ts, body_md FROM log_entry;
DROP TABLE log_entry;
ALTER TABLE log_entry_v6 RENAME TO log_entry;
CREATE INDEX idx_log_project ON log_entry(project_id);
"""

# v7: chains of argument — claim→claim relations so a thesis can depend on
# lemmas or contradict another claim. Evidence (claim_evidence) still only
# ever points at citations/runs; relations are structure, not proof.
_SCHEMA_V7 = """
CREATE TABLE claim_relation (
    id         INTEGER PRIMARY KEY,
    claim_id   INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    related_id INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL DEFAULT 'depends_on'
               CHECK(kind IN ('depends_on','contradicts')),
    UNIQUE(claim_id, related_id, kind),
    CHECK(claim_id != related_id)
);
"""

MIGRATIONS = [_SCHEMA_V1, _SCHEMA_V2, _SCHEMA_V3, _SCHEMA_V4, _SCHEMA_V5,
              _SCHEMA_V6, _SCHEMA_V7]


# --- time & hashing ----------------------------------------------------------
def now() -> str:
    """UTC timestamp, ISO-8601, second precision — stable and sortable."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_hash(obj) -> str:
    """Deterministic sha256 of a JSON-able object (sorted keys)."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# --- connection & migrations -------------------------------------------------
def db_path(root) -> Path:
    return Path(root) / DB_DIRNAME / DB_FILENAME


def connect(root=".", *, read_only: bool = False) -> sqlite3.Connection:
    """Open the env DB with safe pragmas. Writers are migrated forward.

    A read-only connection (``mode=ro``) is used by the ``query`` tool so no
    client can run arbitrary write SQL against the ground truth.
    """
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    if read_only:
        # query_only on a normal connection — reliable with WAL, unlike mode=ro,
        # which can fail to create the -wal/-shm sidecars.
        con.execute("PRAGMA query_only=ON")
    else:
        con.execute("PRAGMA journal_mode=WAL")
        _migrate(con)
    return con


def _migrate(con: sqlite3.Connection) -> None:
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version >= len(MIGRATIONS):
        return
    # Table-rebuild migrations DROP+rename; with FKs on, the DROP would cascade
    # into child tables. SQLite's recipe: FKs off for the pass, verify after.
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        for i in range(version, len(MIGRATIONS)):
            # Each step is atomic (BEGIN…COMMIT around DDL + version bump): a
            # partial failure rolls back entirely instead of leaving added
            # columns behind with a stale user_version, bricking the next open.
            con.executescript(
                f"BEGIN;\n{MIGRATIONS[i]}\nPRAGMA user_version = {i + 1};\nCOMMIT;")
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"migration left {len(bad)} dangling foreign keys")
    finally:
        con.execute("PRAGMA foreign_keys=ON")


def schema_version(con: sqlite3.Connection) -> int:
    return con.execute("PRAGMA user_version").fetchone()[0]


# --- small helpers shared by the domain modules ------------------------------
def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def ensure_project(con: sqlite3.Connection, slug: str, title: str | None = None) -> int:
    """Get the id of project ``slug``, creating it if absent."""
    row = con.execute("SELECT id FROM project WHERE slug=?", (slug,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO project (slug, title, created) VALUES (?,?,?)",
        (slug, title or slug, now()),
    )
    con.commit()
    return cur.lastrowid


def project_id(con: sqlite3.Connection, slug: str) -> int:
    row = con.execute("SELECT id FROM project WHERE slug=?", (slug,)).fetchone()
    if not row:
        raise KeyError(f"no project {slug!r} — create it with `reref project new {slug}`")
    return row["id"]


def get_or_create_config(con: sqlite3.Connection, params: dict) -> int:
    """Insert a config row, deduplicated by canonical hash (one config, many runs)."""
    h = canonical_hash(params)
    row = con.execute("SELECT id FROM config WHERE hash=?", (h,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO config (hash, params_json) VALUES (?,?)",
        (h, json.dumps(params, sort_keys=True)),
    )
    con.commit()
    return cur.lastrowid


# --- deterministic git export (round-trippable; optionally project-scoped) ----
_RUNS = ("(SELECT id FROM run WHERE experiment_id IN "
         "(SELECT id FROM experiment WHERE project_id=:pid))")
# Per-table WHERE for a project slice. Tables absent here are global (export all):
# paper, card, dataset, config.
_PROJECT_FILTER = {
    "project": "id = :pid",
    "experiment": "project_id = :pid",
    "run": "experiment_id IN (SELECT id FROM experiment WHERE project_id=:pid)",
    "metric": f"run_id IN {_RUNS}",
    "artifact": f"run_id IN {_RUNS}",
    "citation": "project_id = :pid",
    "claim": "project_id = :pid",
    "claim_evidence": "claim_id IN (SELECT id FROM claim WHERE project_id=:pid)",
    "log_entry": "project_id = :pid",
    "log_evidence": "log_entry_id IN (SELECT id FROM log_entry WHERE project_id=:pid)",
    "note": "project_id = :pid",
    "review_run": "project_id = :pid",
    "finding": "project_id = :pid",
    "finding_evidence": "finding_id IN (SELECT id FROM finding WHERE project_id=:pid)",
    "adjudication": "finding_id IN (SELECT id FROM finding WHERE project_id=:pid)",
}


def export(con: sqlite3.Connection, root=".", project: str | None = None) -> Path:
    """Write one JSONL per table (rows by id, sorted keys) for git diffs.

    Full export → ``.research/export/``. With ``project``, a *slice* (that project's
    rows + the global corpus tables) → ``projects/<slug>/export/``.
    """
    if project:
        params = {"pid": project_id(con, project)}
        out = Path(root) / "projects" / project / "export"
    else:
        params, out = {}, Path(root) / DB_DIRNAME / EXPORT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        where = _PROJECT_FILTER.get(table) if project else None
        sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + " ORDER BY id"
        rows = con.execute(sql, params).fetchall()
        lines = [json.dumps(dict(r), sort_keys=True) for r in rows]
        (out / f"{table}.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))
    return out


def import_jsonl(con: sqlite3.Connection, root=".", source: Path | None = None) -> int:
    """Rebuild the DB from a JSONL export — the inverse of export(). Idempotent
    (INSERT OR REPLACE), inserts in dependency order. Returns rows loaded."""
    src = Path(source) if source else Path(root) / DB_DIRNAME / EXPORT_DIRNAME
    if not src.exists():
        raise FileNotFoundError(f"no export at {src} — run `reref export` first")
    con.execute("PRAGMA foreign_keys=OFF")
    loaded = 0
    for table in TABLES:
        f = src / f"{table}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            cols = list(row)
            con.execute(
                f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
            loaded += 1
    con.execute("PRAGMA foreign_keys=ON")
    con.commit()
    return loaded
