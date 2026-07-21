"""The central store: one SQLite database = the single ground truth.

The structured state of the whole environment is relational (configs linked to
runs, runs to datasets, citations to papers), so it lives in one embedded SQLite
file under ``<root>/.research/env.db``. All three clients — the ``renv`` CLI, the
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
    "project", "paper", "card", "paper_reference", "dataset", "experiment",
    "config", "run", "metric", "metric_def", "artifact", "citation", "claim",
    "claim_evidence", "claim_relation", "experiment_test", "log_entry",
    "log_evidence", "note", "review_run", "finding", "finding_evidence",
    "adjudication", "plan_item", "remote", "context_link", "paper_note",
    "paper_doc",
]

# Deliberately NOT exported: pure presentation state (canvas positions and
# geometry). Everything else the store knows must be in TABLES — an invariant
# test compares this pair against the live schema, so a new table cannot be
# silently left out of the committed snapshot.
PRESENTATION_TABLES = {"graph_layout", "graph_region", "phase_band"}

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

# v8: relations carry an optional comment (WHY does this depend on that?) —
# rendered on the graph edge, same role claim_evidence.note plays for evidence.
# Plus graph_layout: hand-placed canvas positions per node (presentation state,
# not research truth — but it should survive reloads and be shared by clients).
_SCHEMA_V8 = """
ALTER TABLE claim_relation ADD COLUMN note TEXT;
CREATE TABLE graph_layout (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    node_id    TEXT NOT NULL,
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    UNIQUE(project_id, node_id)
);
"""

# v9: prose is editable, honestly — log entries and notes carry an `edited`
# timestamp (body text only; type/evidence/answers stay immutable ledger
# structure). Created and last-edited are both always visible.
_SCHEMA_V9 = """
ALTER TABLE log_entry ADD COLUMN edited TEXT;
ALTER TABLE note ADD COLUMN edited TEXT;
"""

# v10: project planning — phases (start→due) and milestones (a date), e.g.
# conference deadlines. Deliberately decoupled from claims/log: a plan is
# intent ("what should be done until when"), not evidence. Status is stored
# only as planned|done; active/overdue are DERIVED from dates in the clients.
_SCHEMA_V10 = """
CREATE TABLE plan_item (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'phase' CHECK(kind IN ('phase','milestone')),
    start      TEXT,
    due        TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','done')),
    note       TEXT,
    created    TEXT NOT NULL,
    edited     TEXT
);
CREATE INDEX idx_plan_project ON plan_item(project_id);
"""

# v11: deadlines are first-class plan items — standalone (kind='deadline') or
# attached to a phase's end (end_deadline=1). A deadline can be marked
# `prepared` (ready for it?) independently of done. Rebuild: kind CHECK grows.
_SCHEMA_V11 = """
CREATE TABLE plan_item_v11 (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'phase'
                 CHECK(kind IN ('phase','milestone','deadline')),
    start        TEXT,
    due          TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','done')),
    prepared     INTEGER NOT NULL DEFAULT 0,
    end_deadline INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    created      TEXT NOT NULL,
    edited       TEXT
);
INSERT INTO plan_item_v11 (id, project_id, title, kind, start, due, status, note, created, edited)
    SELECT id, project_id, title, kind, start, due, status, note, created, edited FROM plan_item;
DROP TABLE plan_item;
ALTER TABLE plan_item_v11 RENAME TO plan_item;
CREATE INDEX idx_plan_project ON plan_item(project_id);
"""

# v12: cluster-resident compute AND data — `run.remote` records where a run
# executed / its artifacts live (e.g. ssh://cluster/scratch/runs/exp42), and
# `dataset.location` records where the data lives when it never touches this
# machine (hash supplied by the remote wrapper keeps pinning intact).
_SCHEMA_V12 = """
ALTER TABLE run ADD COLUMN remote TEXT;
ALTER TABLE dataset ADD COLUMN location TEXT;
"""

# v13: the remote registry — named compute/storage locations referencing the
# user's ssh aliases (we never reinvent ssh config, just point at it). A
# remote's data_root lets locators be shorthand: "snaga:runs/exp42" expands
# under /scratch/…; host NULL means this machine.
_SCHEMA_V13 = """
CREATE TABLE remote (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    host        TEXT,
    data_root   TEXT,
    description TEXT,
    created     TEXT NOT NULL
);
"""

# v14: plan sub-items — a phase can contain child items (steps, sub-phases);
# deleting the phase cascades. One level of nesting is the intent.
_SCHEMA_V14 = """
ALTER TABLE plan_item ADD COLUMN parent_id INTEGER REFERENCES plan_item(id) ON DELETE CASCADE;
"""

# v15: context links — soft, annotative connections between graph entities
# (feedback relates-to a claim, a note is about an experiment, a question
# concerns a paper). NOT evidence: they never change a claim's derived status;
# they just record that two things are related. Evidence (claim_evidence) and
# argument structure (claim_relation) stay the strong, typed connections.
_SCHEMA_V15 = """
CREATE TABLE context_link (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    from_kind  TEXT NOT NULL,
    from_id    INTEGER NOT NULL,
    to_kind    TEXT NOT NULL,
    to_id      INTEGER NOT NULL,
    relation   TEXT NOT NULL,
    note       TEXT,
    created    TEXT NOT NULL
);
CREATE INDEX idx_ctxlink_project ON context_link(project_id);
"""

# v16: graph regions — labeled, colored frames on the canvas for visual
# grouping by phase or field. Pure presentation: membership is geometric (a
# node inside the box reads as grouped), never a stored join, so the graph
# stays a view of the store.
_SCHEMA_V16 = """
CREATE TABLE graph_region (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    label      TEXT NOT NULL DEFAULT '',
    color      TEXT NOT NULL DEFAULT 'slate',
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    w          REAL NOT NULL,
    h          REAL NOT NULL,
    created    TEXT NOT NULL
);
CREATE INDEX idx_region_project ON graph_region(project_id);
"""

# A region (graph frame) may name the plan phase it stands for, tying the
# canvas grouping to a Gantt row. ON DELETE SET NULL: deleting the phase just
# unlinks; the region survives. NULL default keeps ADD COLUMN legal with FKs.
_SCHEMA_V17 = """
ALTER TABLE graph_region ADD COLUMN plan_item_id INTEGER
    REFERENCES plan_item(id) ON DELETE SET NULL;
"""

# Positional annotations on a paper: a note anchored to a text span (the same
# W3C quote/prefix/suffix selector citations use) so it re-highlights on the
# rendered PDF. Project-scoped so a note joins that project's graph, where it
# can motivate an experiment or support a claim. Paper delete cascades.
_SCHEMA_V18 = """
CREATE TABLE paper_note (
    id         INTEGER PRIMARY KEY,
    paper_id   INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES project(id) ON DELETE CASCADE,
    page       INTEGER,
    quote      TEXT NOT NULL,
    prefix     TEXT,
    suffix     TEXT,
    src_start  INTEGER,
    src_end    INTEGER,
    color      TEXT NOT NULL DEFAULT 'amber',
    body_md    TEXT NOT NULL DEFAULT '',
    created    TEXT NOT NULL,
    edited     TEXT
);
CREATE INDEX idx_pnote_paper ON paper_note(paper_id);
CREATE INDEX idx_pnote_project ON paper_note(project_id);
"""

# A paper annotation is a note, a question, or a hypothesis — same anchor, same
# graph-node machinery, different intent. Default 'note' keeps existing rows.
_SCHEMA_V19 = """
ALTER TABLE paper_note ADD COLUMN kind TEXT NOT NULL DEFAULT 'note';
"""

# A note document: long-form markdown attached to a paper (project-scoped),
# opened as its own tab. Unlike a positional annotation it isn't anchored to one
# span — it's a writing surface that cites many passages from the paper.
_SCHEMA_V20 = """
CREATE TABLE paper_doc (
    id         INTEGER PRIMARY KEY,
    paper_id   INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES project(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT 'Untitled note',
    body_md    TEXT NOT NULL DEFAULT '',
    created    TEXT NOT NULL,
    edited     TEXT
);
CREATE INDEX idx_pdoc_paper ON paper_doc(paper_id);
CREATE INDEX idx_pdoc_project ON paper_doc(project_id);
"""

# v21: the hypothesis becomes a first-class claim kind, and `experiment_test`
# records — BEFORE any run — which claims an experiment is meant to test
# (pre-registration). Evidence attached later to a declared claim is
# confirmatory in spirit; evidence attached to undeclared claims is exploratory
# (post-hoc), and the lint layer can tell the two apart. Rebuild: kind CHECK
# grows (SQLite's documented recipe, same as v6/v11).
_SCHEMA_V21 = """
CREATE TABLE claim_v21 (
    id        INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    text      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'assertion'
              CHECK(kind IN ('thesis','contribution','assertion','hypothesis')),
    manuscript_loc TEXT,
    status    TEXT NOT NULL DEFAULT 'open'
              CHECK(status IN ('open','supported','refuted')),
    created   TEXT NOT NULL
);
INSERT INTO claim_v21 (id, project_id, text, kind, manuscript_loc, status, created)
    SELECT id, project_id, text, kind, manuscript_loc, status, created FROM claim;
DROP TABLE claim;
ALTER TABLE claim_v21 RENAME TO claim;

CREATE TABLE experiment_test (
    id            INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiment(id) ON DELETE CASCADE,
    claim_id      INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    created       TEXT NOT NULL,
    UNIQUE(experiment_id, claim_id)
);
"""

# v22: the evidence lifecycle. Evidence gains a strength grade (a 1-seed toy
# run is not a 5-seed sweep), an 'inconclusive' stance (the honest middle
# outcome), retraction with a required reason (a superseded run must not veto
# a claim forever), a stale flag (set when the claim's wording changes after
# evidence was attached), and `preregistered` (was this claim declared as
# tested by the run's experiment BEFORE linking?). Status derivation ignores
# retracted rows. Rebuild: stance CHECK grows.
_SCHEMA_V22 = """
CREATE TABLE claim_evidence_v22 (
    id        INTEGER PRIMARY KEY,
    claim_id  INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    citation_id INTEGER REFERENCES citation(id) ON DELETE CASCADE,
    run_id    INTEGER REFERENCES run(id) ON DELETE CASCADE,
    stance    TEXT NOT NULL DEFAULT 'supports'
              CHECK(stance IN ('supports','refutes','inconclusive')),
    grade     TEXT NOT NULL DEFAULT 'suggestive'
              CHECK(grade IN ('anecdotal','suggestive','confirmatory')),
    preregistered INTEGER NOT NULL DEFAULT 0,
    stale     INTEGER NOT NULL DEFAULT 0,
    retracted TEXT,
    retract_reason TEXT,
    superseded_by INTEGER REFERENCES claim_evidence(id) ON DELETE SET NULL,
    note      TEXT,
    created   TEXT,
    CHECK(citation_id IS NOT NULL OR run_id IS NOT NULL)
);
INSERT INTO claim_evidence_v22 (id, claim_id, citation_id, run_id, stance, note)
    SELECT id, claim_id, citation_id, run_id, stance, note FROM claim_evidence;
DROP TABLE claim_evidence;
ALTER TABLE claim_evidence_v22 RENAME TO claim_evidence;
"""

# v23: context links stop rotting — duplicates are removed and a UNIQUE index
# refuses re-inserting the same edge. (Endpoints stay polymorphic, so real FKs
# are impossible; the lint layer audits for dangling endpoints instead.)
_SCHEMA_V23 = """
DELETE FROM context_link WHERE id NOT IN (
    SELECT MIN(id) FROM context_link
    GROUP BY project_id, from_kind, from_id, to_kind, to_id, relation);
CREATE UNIQUE INDEX idx_ctxlink_unique ON context_link
    (project_id, from_kind, from_id, to_kind, to_id, relation);
"""

# v24: phase bands — a plan phase (plan_item kind='phase') projected onto the
# graph canvas as a full-height x-interval. ONE phase entity, three views:
# Gantt row (time), canvas band (space), region link (v17). Membership stays
# geometric (a node's saved x decides its phase), same philosophy as regions,
# but computed server-side so lint rules can reason about phase order.
_SCHEMA_V24 = """
CREATE TABLE phase_band (
    id           INTEGER PRIMARY KEY,
    plan_item_id INTEGER NOT NULL UNIQUE REFERENCES plan_item(id) ON DELETE CASCADE,
    x0           REAL NOT NULL,
    x1           REAL NOT NULL,
    created      TEXT NOT NULL
);
"""

# v25: a band may carry an explicit color (same palette as regions); '' means
# auto — the client assigns by left-to-right ordinal.
_SCHEMA_V25 = """
ALTER TABLE phase_band ADD COLUMN color TEXT NOT NULL DEFAULT '';
"""

# v26: citations are retracted, never deleted — a physical DELETE would cascade
# into claim_evidence (ON DELETE CASCADE) and erase evidence history, which the
# store promises to keep. `citation rm` tombstones the row instead; live views
# (sidecar, usage map, evidence gates) filter on retracted IS NULL.
_SCHEMA_V26 = """
ALTER TABLE citation ADD COLUMN retracted TEXT;
ALTER TABLE citation ADD COLUMN retract_reason TEXT;
"""

# v27: the reader's reference intelligence. A corpus paper's parsed reference
# list becomes rows (numeric [N] entries + extracted arXiv/DOI), matched against
# the paper table; the human can dismiss an entry as not_relevant WITH a comment.
# Status (library / unknown / not_relevant) is derived, never stored. Papers
# added from the reader are inbox'd (paper.inbox) until a human marks them read
# (paper.read_at) — agent-ingested is not human-read.
_SCHEMA_V27 = """
CREATE TABLE paper_reference (
    id               INTEGER PRIMARY KEY,
    paper_id         INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    num              INTEGER,
    raw              TEXT NOT NULL,
    arxiv            TEXT,
    doi              TEXT,
    ref_start        INTEGER,
    ref_end          INTEGER,
    matched_paper_id INTEGER REFERENCES paper(id) ON DELETE SET NULL,
    verdict          TEXT CHECK(verdict IN ('not_relevant')),
    verdict_comment  TEXT,
    fingerprint      TEXT NOT NULL,
    created          TEXT NOT NULL
);
CREATE INDEX idx_paper_reference_paper ON paper_reference(paper_id);
ALTER TABLE paper ADD COLUMN inbox INTEGER NOT NULL DEFAULT 0;
ALTER TABLE paper ADD COLUMN read_at TEXT;
"""

MIGRATIONS = [_SCHEMA_V1, _SCHEMA_V2, _SCHEMA_V3, _SCHEMA_V4, _SCHEMA_V5,
              _SCHEMA_V6, _SCHEMA_V7, _SCHEMA_V8, _SCHEMA_V9, _SCHEMA_V10,
              _SCHEMA_V11, _SCHEMA_V12, _SCHEMA_V13, _SCHEMA_V14, _SCHEMA_V15,
              _SCHEMA_V16, _SCHEMA_V17, _SCHEMA_V18, _SCHEMA_V19, _SCHEMA_V20,
              _SCHEMA_V21, _SCHEMA_V22, _SCHEMA_V23, _SCHEMA_V24, _SCHEMA_V25,
              _SCHEMA_V26, _SCHEMA_V27]


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
    if not path.exists():
        # refuse to create a NEW store inside an existing env (e.g. running
        # from cockpit/): the silent empty-DB-in-a-subdir failure mode.
        for anc in Path(root).resolve().parents:
            if (anc / DB_DIRNAME).is_dir():
                raise RuntimeError(
                    f"refusing to create {path} — an env already exists at {anc}; "
                    "run from the env root or pass --corpus")
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
        raise KeyError(f"no project {slug!r} — create it with `renv project new {slug}`")
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
    "experiment_test": "claim_id IN (SELECT id FROM claim WHERE project_id=:pid)",
    "log_entry": "project_id = :pid",
    "log_evidence": "log_entry_id IN (SELECT id FROM log_entry WHERE project_id=:pid)",
    "note": "project_id = :pid",
    "review_run": "project_id = :pid",
    "finding": "project_id = :pid",
    "finding_evidence": "finding_id IN (SELECT id FROM finding WHERE project_id=:pid)",
    "adjudication": "finding_id IN (SELECT id FROM finding WHERE project_id=:pid)",
    "claim_relation": "claim_id IN (SELECT id FROM claim WHERE project_id=:pid)",
    "plan_item": "project_id = :pid",
    "context_link": "project_id = :pid",
    "paper_note": "project_id = :pid",
    "paper_doc": "project_id = :pid",
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
        raise FileNotFoundError(f"no export at {src} — run `renv export` first")
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
