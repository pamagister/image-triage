"""SQLite schema definition and connection setup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start       TEXT NOT NULL,
    "end"       TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'time',
    photo_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    method       TEXT NOT NULL DEFAULT 'similarity',
    version      TEXT NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,
    digest          TEXT NOT NULL,
    taken           TEXT NOT NULL,
    width           INTEGER NOT NULL DEFAULT 0,
    height          INTEGER NOT NULL DEFAULT 0,
    camera_make     TEXT,
    camera_model    TEXT,
    gps_lat         REAL,
    gps_lon         REAL,
    event_id        INTEGER REFERENCES events(id) ON DELETE SET NULL,
    group_id        INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    score           REAL NOT NULL DEFAULT 0,
    rating          INTEGER NOT NULL DEFAULT 0,
    flags           TEXT NOT NULL DEFAULT '[]',
    model_signature TEXT,
    analyzed_at     TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    photo_id              INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    sharpness             REAL NOT NULL DEFAULT 0,
    sharpness_raw         REAL NOT NULL DEFAULT 0,
    blur_kind             TEXT NOT NULL DEFAULT 'none',
    blur_confidence       REAL NOT NULL DEFAULT 0,
    composition           REAL NOT NULL DEFAULT 0,
    composition_components TEXT NOT NULL DEFAULT '{}',
    aesthetic             REAL NOT NULL DEFAULT 0,
    aesthetic_source      TEXT NOT NULL DEFAULT 'heuristic',
    subject_score         REAL NOT NULL DEFAULT 0,
    subject_rarity        REAL NOT NULL DEFAULT 0,
    exposure              REAL NOT NULL DEFAULT 0,
    metric_version        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    confidence REAL NOT NULL,
    x1         REAL NOT NULL,
    y1         REAL NOT NULL,
    x2         REAL NOT NULL,
    y2         REAL NOT NULL,
    area       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    photo_id  INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    dim       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS photo_events (
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, event_id)
);

CREATE TABLE IF NOT EXISTS photo_groups (
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, group_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    command      TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    config_hash  TEXT NOT NULL DEFAULT '',
    model_hashes TEXT NOT NULL DEFAULT '{}',
    counts       TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS selections (
    run_id     TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    rank       INTEGER NOT NULL,
    score      REAL NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    quota_rule TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, photo_id)
);

CREATE TABLE IF NOT EXISTS overrides (
    photo_id   INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    rating     INTEGER,
    keep       INTEGER,
    source     TEXT NOT NULL DEFAULT 'cli',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    payload    TEXT NOT NULL DEFAULT '{}',
    progress   REAL NOT NULL DEFAULT 0,
    result     TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken);
CREATE INDEX IF NOT EXISTS idx_photos_digest ON photos(digest);
CREATE INDEX IF NOT EXISTS idx_photos_event ON photos(event_id);
CREATE INDEX IF NOT EXISTS idx_photos_group ON photos(group_id);
CREATE INDEX IF NOT EXISTS idx_photos_score ON photos(score DESC);
CREATE INDEX IF NOT EXISTS idx_photos_rating ON photos(rating DESC);
CREATE INDEX IF NOT EXISTS idx_detections_photo ON detections(photo_id);
CREATE INDEX IF NOT EXISTS idx_photo_groups_group ON photo_groups(group_id);
CREATE INDEX IF NOT EXISTS idx_photo_events_event ON photo_events(event_id);
CREATE INDEX IF NOT EXISTS idx_selections_run ON selections(run_id, rank);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL, foreign keys and a busy timeout enabled."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def read_version(connection: sqlite3.Connection) -> int:
    """Return the stored schema version, or 0 for a fresh database."""
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row["value"]) if row else 0


def write_version(connection: sqlite3.Connection, version: int) -> None:
    """Persist the schema version."""
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )
