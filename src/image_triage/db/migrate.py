"""Forward-only SQLite migrations."""

from __future__ import annotations

import sqlite3

from image_triage.db.schema import (
    INITIAL_SCHEMA,
    METRICS_V2,
    SCHEMA_VERSION,
    read_version,
    write_version,
)

# Version -> SQL script. Add new versions here and bump SCHEMA_VERSION.
MIGRATIONS: dict[int, str] = {1: INITIAL_SCHEMA, 2: METRICS_V2}


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
    return SCHEMA_VERSION
