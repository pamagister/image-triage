"""Forward-only SQLite migrations."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from image_triage.db.schema import (
    BLUR_V3,
    INITIAL_SCHEMA,
    METRICS_V2,
    SCHEMA_V3_INDEXES,
    SCHEMA_V3_TABLES,
    SCHEMA_VERSION,
    read_version,
    write_version,
)

# Version -> SQL script. Add new versions here and bump SCHEMA_VERSION.
MIGRATIONS: dict[int, str] = {1: INITIAL_SCHEMA, 2: METRICS_V2}

#: Tables whose rows reference a photo and must drop duplicates during the v3 rebuild.
_CHILD_TABLES = (
    "metrics",
    "detections",
    "embeddings",
    "photo_events",
    "photo_groups",
    "overrides",
    "selections",
)

_PHOTO_COLUMNS = """
    id, digest, phash, taken, width, height, camera_make, camera_model,
    gps_lat, gps_lon, event_id, group_id, score, rating, flags,
    model_signature, analyzed_at, created_at
"""


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    """Rebuild a path-addressed version 2 database into the content-addressed model.

    Duplicate digests collapse to the oldest row. Their paths become locations of the
    surviving content row, so ratings and metrics are shared. Rows with an empty digest
    keep a synthetic ``legacy:<path>`` identity because no content hash is available.
    """
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.executescript(SCHEMA_V3_TABLES)
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO roots (path, label, created_at) "
        "SELECT '', 'migrated', ? WHERE EXISTS (SELECT 1 FROM photos) "
        "AND NOT EXISTS (SELECT 1 FROM roots WHERE path = '')",
        (now,),
    )
    root = connection.execute("SELECT id FROM roots WHERE path = ''").fetchone()
    if root is not None:
        connection.execute(
            "CREATE TEMP TABLE v3_kept AS "
            "SELECT key, MIN(id) AS keep_id FROM ("
            "  SELECT id, CASE WHEN digest = '' THEN 'legacy:' || path ELSE digest END AS key "
            "  FROM photos"
            ") GROUP BY key"
        )
        connection.execute(
            f"""
            INSERT INTO photos_v3 ({_PHOTO_COLUMNS})
            SELECT p.id,
                   CASE WHEN p.digest = '' THEN 'legacy:' || p.path ELSE p.digest END,
                   p.phash, p.taken, p.width, p.height, p.camera_make, p.camera_model,
                   p.gps_lat, p.gps_lon, p.event_id, p.group_id, p.score, p.rating,
                   p.flags, p.model_signature, p.analyzed_at, p.created_at
            FROM photos p
            JOIN v3_kept k ON k.keep_id = p.id
            """
        )
        connection.execute(
            """
            INSERT INTO photo_locations
                (photo_id, root_id, relative_path, mtime, analyzed_at, available)
            SELECT k.keep_id, ?, p.path, NULL, p.analyzed_at, 1
            FROM photos p
            JOIN v3_kept k
              ON k.key = CASE WHEN p.digest = '' THEN 'legacy:' || p.path ELSE p.digest END
            """,
            (root["id"],),
        )
        for table in _CHILD_TABLES:
            connection.execute(
                f"DELETE FROM {table} WHERE photo_id NOT IN (SELECT id FROM photos_v3)"
            )
    connection.execute("DROP TABLE photos")
    connection.execute("ALTER TABLE photos_v3 RENAME TO photos")
    connection.executescript(SCHEMA_V3_INDEXES)
    connection.executescript(BLUR_V3)
    connection.execute("DROP TABLE IF EXISTS v3_kept")
    connection.commit()
    connection.execute("PRAGMA foreign_keys=ON")


def ensure_schema(connection: sqlite3.Connection) -> int:
    """Create or migrate the database and return the resulting schema version."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    current = read_version(connection)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
        )
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        connection.executescript(MIGRATIONS[version])
        write_version(connection, version)
        connection.commit()
        current = version
    if current < 3:
        _migrate_v2_to_v3(connection)
        write_version(connection, 3)
        connection.commit()
    return SCHEMA_VERSION
