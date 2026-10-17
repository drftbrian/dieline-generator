"""SQLite storage. Wrapped so it can later move to Postgres."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    source_json     TEXT,
    spec_json       TEXT,
    spec_version    INTEGER NOT NULL DEFAULT 0,
    error_json      TEXT,
    figma_json      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type             TEXT NOT NULL,
    status           TEXT NOT NULL,
    progress         REAL NOT NULL DEFAULT 0,
    stages           TEXT NOT NULL DEFAULT '[]',
    result           TEXT,
    error            TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refs (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    mime            TEXT NOT NULL,
    width           INTEGER NOT NULL,
    height          INTEGER NOT NULL,
    role            TEXT,
    role_source     TEXT,
    note            TEXT NOT NULL DEFAULT '',
    summary         TEXT,
    analysis_status TEXT NOT NULL,
    analysis_json   TEXT,
    position        INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    number           INTEGER NOT NULL,
    parent_id        TEXT,
    status           TEXT NOT NULL,
    provider         TEXT NOT NULL,
    model_id         TEXT NOT NULL,
    mode             TEXT NOT NULL,
    settings_json    TEXT NOT NULL,
    reference_ids    TEXT NOT NULL,
    spec_version     INTEGER NOT NULL,
    job_id           TEXT,
    usage_json       TEXT,
    verify_json      TEXT,
    frame_json       TEXT,
    error_json       TEXT,
    starred          INTEGER NOT NULL DEFAULT 0,
    name             TEXT,
    deleted_at       TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    key         TEXT PRIMARY KEY,
    scope       TEXT NOT NULL,
    status      INTEGER NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


MIGRATIONS = [
    ("projects", "figma_json", "TEXT"),
    ("refs", "analysis_json", "TEXT"),
    ("versions", "kind", "TEXT DEFAULT 'flat'"),
    ("versions", "scene_json", "TEXT"),
    ("refs", "scene_json", "TEXT"),
    ("refs", "purpose", "TEXT"),  # unused since the 3-step app; old rows keep it
    ("versions", "flat_version_id", "TEXT"),  # merge: the approved flat render it was made from
]
# Tables of removed features (instructions, export, the watched reference folder). Their files on disk
# are left alone; the rows are dropped.
DROPPED = ["instructions", "exports", "library_items"]


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for table in DROPPED:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        # Additive migrations for databases created by earlier versions.
        for table, column, decl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
