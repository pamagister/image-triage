"""Typed SQLite repository for photos, metrics, groups, events, runs and selections."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from image_triage.core.models import (
    METRIC_VERSION,
    BlurKind,
    Detection,
    Event,
    Metrics,
    Override,
    OverrideSource,
    Photo,
    PhotoLocation,
    Run,
    RunStatus,
    Selection,
)
from image_triage.db.migrate import ensure_schema
from image_triage.db.schema import connect


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used for deterministic ordering."""
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


_METRICS_COLUMNS = """
    m.sharpness, m.sharpness_raw, m.sharpness_subject, m.sharpness_subject_raw,
    m.bokeh, m.blur_kind, m.blur_confidence, m.blur_score,
    m.composition, m.composition_components, m.aesthetic, m.aesthetic_source,
    m.subject_score, m.subject_rarity, m.exposure
"""

_CONTENT_SELECT = (
    """
    SELECT p.*,
    """
    + _METRICS_COLUMNS
    + """,
           (SELECT l.id FROM photo_locations l
            WHERE l.photo_id = p.id AND l.available = 1
            ORDER BY l.relative_path LIMIT 1) AS location_id,
           (SELECT l.root_id FROM photo_locations l
            WHERE l.photo_id = p.id AND l.available = 1
            ORDER BY l.relative_path LIMIT 1) AS root_id,
           (SELECT l.relative_path FROM photo_locations l
            WHERE l.photo_id = p.id AND l.available = 1
            ORDER BY l.relative_path LIMIT 1) AS path,
           (SELECT r.path FROM photo_locations l
            JOIN roots r ON r.id = l.root_id
            WHERE l.photo_id = p.id AND l.available = 1
            ORDER BY l.relative_path LIMIT 1) AS root_path,
           (SELECT l.available FROM photo_locations l
            WHERE l.photo_id = p.id AND l.available = 1
            ORDER BY l.relative_path LIMIT 1) AS available
    FROM photos p
    LEFT JOIN metrics m ON m.photo_id = p.id
    """
)

_LOCATION_SELECT = (
    """
    SELECT p.*, l.id AS location_id, l.root_id, l.relative_path AS path,
           l.available, r.path AS root_path,
    """
    + _METRICS_COLUMNS
    + """
    FROM photo_locations l
    JOIN photos p ON p.id = l.photo_id
    JOIN roots r ON r.id = l.root_id
    LEFT JOIN metrics m ON m.photo_id = p.id
    """
)


class Repository:
    """All database access used by the pipeline, CLI and GUI."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @classmethod
    def open(cls, db_path: str | Path) -> Repository:
        """Open a database, create the schema and return a repository."""
        connection = connect(db_path)
        ensure_schema(connection)
        return cls(connection)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    # ------------------------------------------------------------------ photos

    def _ensure_root(self, path: str, *, label: str = "", enabled: bool = True) -> int:
        """Return the root id for ``path``, creating the row when needed."""
        row = self.connection.execute(
            "SELECT id FROM roots WHERE path = ?", (str(path),)
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = self.connection.execute(
            "INSERT INTO roots (path, label, enabled, created_at) VALUES (?, ?, ?, ?)",
            (str(path), label, int(enabled), _iso(utcnow())),
        )
        return int(cursor.lastrowid)

    def sync_roots(self, paths: list[Path]) -> list[dict[str, Any]]:
        """Add configured roots and disable roots that are no longer watched."""
        if not paths:
            return self.roots()
        wanted = [str(path) for path in paths]
        with self.connection:
            migrated = self.connection.execute(
                "SELECT id FROM roots WHERE path = '' AND enabled = 1"
            ).fetchall()
            for path in wanted:
                self._ensure_root(path)
            if migrated:
                # A migrated or legacy single-root database adopts the first configured root.
                self.connection.execute(
                    "UPDATE roots SET path = ? WHERE id = ?", (wanted[0], migrated[0]["id"])
                )
            placeholders = ", ".join("?" for _ in wanted)
            self.connection.execute(
                "UPDATE roots SET enabled = CASE WHEN path IN ("
                + placeholders
                + ") THEN 1 ELSE 0 END",
                wanted,
            )
        return self.roots()

    def roots(self) -> list[dict[str, Any]]:
        """All roots with their enabled state and available photo count."""
        rows = self.connection.execute(
            """
            SELECT r.id, r.path, r.label, r.enabled,
                   COUNT(l.id) AS photos
            FROM roots r
            LEFT JOIN photo_locations l
              ON l.root_id = r.id AND l.available = 1
            GROUP BY r.id
            ORDER BY r.path
            """
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "path": row["path"],
                "label": row["label"],
                "enabled": bool(row["enabled"]),
                "photos": int(row["photos"] or 0),
            }
            for row in rows
        ]

    def upsert_location(
        self,
        photo_id: int,
        root_path: str,
        relative_path: str,
        *,
        mtime: float | None = None,
        analyzed_at: str | None = None,
        available: bool = True,
        commit: bool = True,
    ) -> int:
        """Insert or update one content location."""
        root_id = self._ensure_root(root_path)
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO photo_locations
                    (photo_id, root_id, relative_path, mtime, analyzed_at, available)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_id, relative_path) DO UPDATE SET
                    photo_id=excluded.photo_id,
                    mtime=excluded.mtime,
                    analyzed_at=excluded.analyzed_at,
                    available=excluded.available
                RETURNING id
                """,
                (photo_id, root_id, relative_path, mtime, analyzed_at, int(available)),
            )
            location_id = int(cursor.fetchone()[0])
        if commit:
            self.connection.commit()
        return location_id

    def upsert_scanned_location(
        self,
        photo_id: int,
        root_path: str,
        relative_path: str,
        *,
        digest: str,
        keep: set[tuple[str, str]],
        mtime: float | None = None,
        analyzed_at: str | None = None,
        commit: bool = True,
    ) -> int:
        """Insert a scanned location, repointing a missing location with the same digest.

        A moved file keeps its content record and location id; only the path changes.
        """
        root_id = self._ensure_root(root_path)
        existing = self.connection.execute(
            "SELECT id FROM photo_locations WHERE root_id = ? AND relative_path = ?",
            (root_id, relative_path),
        ).fetchone()
        if existing is not None:
            with self.connection:
                self.connection.execute(
                    "UPDATE photo_locations SET photo_id = ?, mtime = ?, analyzed_at = ?, "
                    "available = 1 WHERE id = ?",
                    (photo_id, mtime, analyzed_at, existing["id"]),
                )
            if commit:
                self.connection.commit()
            return int(existing["id"])
        for location in self.locations_for_digest(digest):
            if (
                location.root_path == str(root_path)
                and location.available
                and (location.root_path, location.relative_path) not in keep
            ):
                with self.connection:
                    self.connection.execute(
                        "UPDATE photo_locations SET photo_id = ?, relative_path = ?, mtime = ?, "
                        "analyzed_at = ?, available = 1 WHERE id = ?",
                        (photo_id, relative_path, mtime, analyzed_at, location.id),
                    )
                if commit:
                    self.connection.commit()
                return location.id
        return self.upsert_location(
            photo_id,
            root_path,
            relative_path,
            mtime=mtime,
            analyzed_at=analyzed_at,
            commit=commit,
        )

    def location_paths(
        self, *, available_only: bool = True
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Map ``(root, relative path)`` to location metadata."""
        sql = (
            "SELECT l.id, l.relative_path, l.mtime, l.analyzed_at, l.available, "
            "r.path AS root_path, p.digest "
            "FROM photo_locations l "
            "JOIN photos p ON p.id = l.photo_id "
            "JOIN roots r ON r.id = l.root_id"
        )
        if available_only:
            sql += " WHERE l.available = 1"
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self.connection.execute(sql):
            result[(row["root_path"], row["relative_path"])] = {
                "id": int(row["id"]),
                "mtime": row["mtime"],
                "analyzed_at": row["analyzed_at"],
                "available": bool(row["available"]),
                "digest": row["digest"],
            }
        return result

    def upsert_photo(
        self,
        photo: Photo,
        *,
        metric_version: str = METRIC_VERSION,
        update_rating: bool = False,
        commit: bool = True,
    ) -> int:
        """Insert or update content-addressed metrics and one optional location.

        ``digest`` is the identity. Re-analysis never clears an existing rating unless
        ``update_rating`` is explicitly requested, so user ratings survive a rescan.
        """
        now = utcnow()
        analyzed_at = photo.analyzed_at or now
        if not photo.digest:
            # Manual inserts without a content hash fall back to a path identity.
            photo.digest = f"legacy:{photo.path}"
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO photos (
                    digest, phash, taken, width, height, camera_make, camera_model,
                    gps_lat, gps_lon, event_id, group_id, score, rating, flags,
                    model_signature, analyzed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(digest) DO UPDATE SET
                    phash=excluded.phash,
                    taken=excluded.taken,
                    width=excluded.width,
                    height=excluded.height,
                    camera_make=excluded.camera_make,
                    camera_model=excluded.camera_model,
                    gps_lat=excluded.gps_lat,
                    gps_lon=excluded.gps_lon,
                    score=excluded.score,
                    flags=excluded.flags,
                    model_signature=excluded.model_signature,
                    analyzed_at=excluded.analyzed_at
                RETURNING id
                """,
                (
                    photo.digest,
                    photo.phash,
                    _iso(photo.taken) or "",
                    photo.width,
                    photo.height,
                    photo.camera_make,
                    photo.camera_model,
                    photo.gps_lat,
                    photo.gps_lon,
                    photo.event_id,
                    photo.group_id,
                    photo.score,
                    photo.rating,
                    json.dumps(photo.flags),
                    photo.model_signature,
                    _iso(analyzed_at),
                    _iso(now),
                ),
            )
            photo.id = int(cursor.fetchone()[0])
            if update_rating:
                self.connection.execute(
                    "UPDATE photos SET rating = ? WHERE id = ?", (photo.rating, photo.id)
                )
            self.connection.execute(
                """
                INSERT INTO metrics (
                    photo_id, sharpness, sharpness_raw, sharpness_subject, sharpness_subject_raw,
                    bokeh, blur_kind, blur_confidence, blur_score, composition,
                    composition_components, aesthetic, aesthetic_source, subject_score,
                    subject_rarity, exposure, metric_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(photo_id) DO UPDATE SET
                    sharpness=excluded.sharpness,
                    sharpness_raw=excluded.sharpness_raw,
                    sharpness_subject=excluded.sharpness_subject,
                    sharpness_subject_raw=excluded.sharpness_subject_raw,
                    bokeh=excluded.bokeh,
                    blur_kind=excluded.blur_kind,
                    blur_confidence=excluded.blur_confidence,
                    blur_score=excluded.blur_score,
                    composition=excluded.composition,
                    composition_components=excluded.composition_components,
                    aesthetic=excluded.aesthetic,
                    aesthetic_source=excluded.aesthetic_source,
                    subject_score=excluded.subject_score,
                    subject_rarity=excluded.subject_rarity,
                    exposure=excluded.exposure,
                    metric_version=excluded.metric_version
                """,
                (
                    photo.id,
                    photo.metrics.sharpness,
                    photo.metrics.sharpness_raw,
                    photo.metrics.sharpness_subject,
                    photo.metrics.sharpness_subject_raw,
                    photo.metrics.bokeh,
                    photo.metrics.blur_kind.value,
                    photo.metrics.blur_confidence,
                    photo.metrics.blur_score,
                    photo.metrics.composition,
                    json.dumps(photo.metrics.composition_components, sort_keys=True),
                    photo.metrics.aesthetic,
                    photo.metrics.aesthetic_source,
                    photo.metrics.subject_score,
                    photo.metrics.subject_rarity,
                    photo.metrics.exposure,
                    metric_version,
                ),
            )
            self.connection.execute("DELETE FROM detections WHERE photo_id = ?", (photo.id,))
            if photo.detections:
                self.connection.executemany(
                    """
                    INSERT INTO detections (photo_id, label, confidence, x1, y1, x2, y2, area)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            photo.id,
                            d.label,
                            d.confidence,
                            d.box[0],
                            d.box[1],
                            d.box[2],
                            d.box[3],
                            d.area,
                        )
                        for d in photo.detections
                    ],
                )
            self.connection.execute("DELETE FROM embeddings WHERE photo_id = ?", (photo.id,))
            if photo.embedding:
                vector = np.asarray(photo.embedding, dtype=np.float32)
                self.connection.execute(
                    "INSERT INTO embeddings (photo_id, embedding, dim) VALUES (?, ?, ?)",
                    (photo.id, vector.tobytes(), int(vector.size)),
                )
        if commit:
            self.connection.commit()
        if photo.path:
            root_path = photo.root_path
            if not root_path and photo.location_id is not None:
                row = self.connection.execute(
                    "SELECT r.path FROM photo_locations l "
                    "JOIN roots r ON r.id = l.root_id WHERE l.id = ?",
                    (photo.location_id,),
                ).fetchone()
                root_path = row["path"] if row else ""
            self.upsert_location(
                photo.id,
                root_path,
                photo.path,
                analyzed_at=_iso(analyzed_at),
                commit=commit,
            )
        return photo.id

    def photo_by_path(self, path: str) -> Photo | None:
        row = self.connection.execute(
            """
            SELECT p.id FROM photo_locations l
            JOIN photos p ON p.id = l.photo_id
            WHERE l.relative_path = ? AND l.available = 1
            ORDER BY l.id LIMIT 1
            """,
            (path,),
        ).fetchone()
        return self.photo_by_id(int(row["id"])) if row else None

    def photo_by_id(self, photo_id: int) -> Photo | None:
        row = self.connection.execute(
            _CONTENT_SELECT + " WHERE p.id = ?",
            (photo_id,),
        ).fetchone()
        return self._row_to_photo(row) if row else None

    def photo_by_location(self, location_id: int) -> Photo | None:
        row = self.connection.execute(
            _LOCATION_SELECT + " WHERE l.id = ?",
            (location_id,),
        ).fetchone()
        return self._row_to_photo(row) if row else None

    def location_by_id(self, location_id: int) -> PhotoLocation | None:
        row = self.connection.execute(
            """
            SELECT l.id, l.photo_id, l.root_id, r.path AS root_path, l.relative_path,
                   l.mtime, l.analyzed_at, l.available
            FROM photo_locations l
            JOIN roots r ON r.id = l.root_id
            WHERE l.id = ?
            """,
            (location_id,),
        ).fetchone()
        if not row:
            return None
        return PhotoLocation(
            id=int(row["id"]),
            photo_id=int(row["photo_id"]),
            root_id=int(row["root_id"]),
            root_path=row["root_path"],
            relative_path=row["relative_path"],
            mtime=row["mtime"],
            analyzed_at=_parse_dt(row["analyzed_at"]),
            available=bool(row["available"]),
        )

    def locations_for_digest(self, digest: str) -> list[PhotoLocation]:
        rows = self.connection.execute(
            """
            SELECT l.id, l.photo_id, l.root_id, r.path AS root_path, l.relative_path,
                   l.mtime, l.analyzed_at, l.available
            FROM photo_locations l
            JOIN photos p ON p.id = l.photo_id
            JOIN roots r ON r.id = l.root_id
            WHERE p.digest = ?
            ORDER BY r.path, l.relative_path
            """,
            (digest,),
        ).fetchall()
        return [
            PhotoLocation(
                id=int(row["id"]),
                photo_id=int(row["photo_id"]),
                root_id=int(row["root_id"]),
                root_path=row["root_path"],
                relative_path=row["relative_path"],
                mtime=row["mtime"],
                analyzed_at=_parse_dt(row["analyzed_at"]),
                available=bool(row["available"]),
            )
            for row in rows
        ]

    def all_photos(self) -> list[Photo]:
        """Every available location, ordered deterministically."""
        rows = self.connection.execute(
            _LOCATION_SELECT + " WHERE l.available = 1 ORDER BY p.taken, r.path, l.relative_path"
        ).fetchall()
        return [self._row_to_photo(row) for row in rows]

    def all_content(self) -> list[Photo]:
        """One row per unique digest, with a representative available location."""
        rows = self.connection.execute(_CONTENT_SELECT + " ORDER BY p.taken, p.id").fetchall()
        return [self._row_to_photo(row) for row in rows]

    def count_content(self) -> int:
        """Number of unique content records."""
        return int(self.connection.execute("SELECT COUNT(*) AS n FROM photos").fetchone()["n"])

    def analyzed_paths(self) -> dict[str, str | None]:
        """Map a representative path to its ``analyzed_at`` timestamp."""
        rows = self.connection.execute(
            """
            SELECT p.analyzed_at,
                   (SELECT l.relative_path FROM photo_locations l
                    WHERE l.photo_id = p.id AND l.available = 1
                    ORDER BY l.relative_path LIMIT 1) AS path
            FROM photos p
            """
        ).fetchall()
        return {row["path"]: row["analyzed_at"] for row in rows if row["path"] is not None}

    def mark_missing_locations(self, keep: set[tuple[str, str]]) -> list[str]:
        """Mark stored locations absent from ``keep`` unavailable; return their labels."""
        rows = self.connection.execute(
            """
            SELECT l.id, l.relative_path, l.available, r.path AS root_path
            FROM photo_locations l
            JOIN roots r ON r.id = l.root_id
            """
        ).fetchall()
        removed: list[str] = []
        ids: list[int] = []
        for row in rows:
            key = (row["root_path"], row["relative_path"])
            if key not in keep:
                removed.append(
                    f"{row['root_path']}/{row['relative_path']}"
                    if row["root_path"] not in {"", "."}
                    else row["relative_path"]
                )
                if row["available"]:
                    ids.append(int(row["id"]))
        if ids:
            with self.connection:
                self.connection.executemany(
                    "UPDATE photo_locations SET available = 0 WHERE id = ?",
                    [(location_id,) for location_id in ids],
                )
        return sorted(removed)

    def delete_missing_photos(self, keep: set[str]) -> list[str]:
        """Backward-compatible wrapper around :meth:`mark_missing_locations`."""
        return self.mark_missing_locations({("", path) for path in keep})

    def gps_points(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT p.id, l.relative_path, r.path AS root_path, p.gps_lat, p.gps_lon
            FROM photo_locations l
            JOIN photos p ON p.id = l.photo_id
            JOIN roots r ON r.id = l.root_id
            WHERE p.gps_lat IS NOT NULL AND p.gps_lon IS NOT NULL AND l.available = 1
            ORDER BY p.taken, r.path, l.relative_path
            """
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "path": row["relative_path"],
                "root": row["root_path"],
                "lat": float(row["gps_lat"]),
                "lon": float(row["gps_lon"]),
            }
            for row in rows
        ]

    def _row_to_photo(self, row: sqlite3.Row) -> Photo:
        flags = json.loads(row["flags"] or "[]")
        components = json.loads(row["composition_components"] or "{}")
        metrics = Metrics(
            sharpness=float(row["sharpness"] or 0.0),
            sharpness_raw=float(row["sharpness_raw"] or 0.0),
            sharpness_subject=float(row["sharpness_subject"] or 0.0),
            sharpness_subject_raw=float(row["sharpness_subject_raw"] or 0.0),
            bokeh=float(row["bokeh"] or 0.0),
            blur_kind=BlurKind(row["blur_kind"] or "none"),
            blur_confidence=float(row["blur_confidence"] or 0.0),
            blur_score=float(row["blur_score"] or 0.0) if "blur_score" in row.keys() else 0.0,
            composition=float(row["composition"] or 0.0),
            composition_components=components,
            aesthetic=float(row["aesthetic"] or 0.0),
            aesthetic_source=row["aesthetic_source"] or "heuristic",
            subject_score=float(row["subject_score"] or 0.0),
            subject_rarity=float(row["subject_rarity"] or 0.0),
            exposure=float(row["exposure"] or 0.0),
        )
        detections = [
            Detection(
                label=det["label"],
                confidence=float(det["confidence"]),
                box=(float(det["x1"]), float(det["y1"]), float(det["x2"]), float(det["y2"])),
            )
            for det in self.connection.execute(
                "SELECT label, confidence, x1, y1, x2, y2 FROM detections WHERE photo_id = ? "
                "ORDER BY confidence DESC, label",
                (row["id"],),
            )
        ]
        embedding: list[float] | None = None
        blob_row = self.connection.execute(
            "SELECT embedding FROM embeddings WHERE photo_id = ?", (row["id"],)
        ).fetchone()
        if blob_row:
            embedding = np.frombuffer(blob_row["embedding"], dtype=np.float32).tolist()
        keys = row.keys()
        return Photo(
            id=int(row["id"]),
            location_id=int(row["location_id"])
            if "location_id" in keys and row["location_id"] is not None
            else None,
            root_id=int(row["root_id"])
            if "root_id" in keys and row["root_id"] is not None
            else None,
            root_path=row["root_path"]
            if "root_path" in keys and row["root_path"] is not None
            else "",
            path=row["path"] if "path" in keys and row["path"] is not None else "",
            digest=row["digest"],
            phash=row["phash"] or "",
            taken=_parse_dt(row["taken"]),
            width=int(row["width"] or 0),
            height=int(row["height"] or 0),
            camera_make=row["camera_make"],
            camera_model=row["camera_model"],
            gps_lat=row["gps_lat"],
            gps_lon=row["gps_lon"],
            event_id=row["event_id"],
            group_id=row["group_id"],
            metrics=metrics,
            detections=detections,
            embedding=embedding,
            score=float(row["score"] or 0.0),
            rating=int(row["rating"] or 0),
            flags=flags,
            model_signature=row["model_signature"],
            analyzed_at=_parse_dt(row["analyzed_at"]),
            available=bool(row["available"])
            if "available" in keys and row["available"] is not None
            else True,
        )

    def _photo_filters(
        self,
        *,
        rating: int | Sequence[int] | None = None,
        event_id: int | Sequence[int] | None = None,
        group_id: int | Sequence[int] | None = None,
        label: str | Sequence[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float | None = None,
        search: str | None = None,
        selected_run: str | None = None,
        blur: str | Sequence[str] | None = None,
        flags: str | Sequence[str] | None = None,
        camera_make: str | Sequence[str] | None = None,
        camera_model: str | Sequence[str] | None = None,
        score_max: float | None = None,
        sharpness_min: float | None = None,
        aesthetic_min: float | None = None,
        subject_min: float | None = None,
        root: str | Sequence[str] | None = None,
        folder: str | Sequence[str] | None = None,
    ) -> tuple[list[str], list[Any]]:
        def values(value: object) -> list[Any]:
            """Accept a scalar or a sequence and return a non-empty list."""
            if value is None:
                return []
            if isinstance(value, (str, int, float)):
                return [] if value == "" else [value]
            return [item for item in value if item is not None and item != ""]  # type: ignore[union-attr]

        def quoted(column: str, items: list[Any]) -> str:
            placeholders = ", ".join("?" for _ in items)
            return f"{column} IN ({placeholders})"

        where: list[str] = ["l.available = 1"]
        params: list[Any] = []
        roots = values(root)
        if roots:
            where.append(quoted("r.path", roots))
            params.extend(roots)
        folders = values(folder)
        for value in folders:
            cleaned = str(value).strip().strip("/")
            if not cleaned:
                continue
            where.append("(l.relative_path = ? OR l.relative_path LIKE ?)")
            params.extend([cleaned, cleaned + "/%"])
        ratings = values(rating)
        if ratings:
            where.append(quoted("p.rating", ratings))
            params.extend(ratings)
        event_ids = values(event_id)
        if event_ids:
            where.append(quoted("p.event_id", event_ids))
            params.extend(event_ids)
        group_ids = values(group_id)
        if group_ids:
            where.append(quoted("p.group_id", group_ids))
            params.extend(group_ids)
        labels = values(label)
        if labels:
            where.append(
                "EXISTS (SELECT 1 FROM detections d WHERE d.photo_id = p.id AND "
                + quoted("d.label", labels)
                + ")"
            )
            params.extend(labels)
        blur_kinds = values(blur)
        if blur_kinds:
            where.append(quoted("m.blur_kind", blur_kinds))
            params.extend(blur_kinds)
        photo_flags = values(flags)
        if photo_flags:
            clauses = " OR ".join(
                "EXISTS (SELECT 1 FROM json_each(p.flags) WHERE value = ?)" for _ in photo_flags
            )
            where.append(f"({clauses})")
            params.extend(photo_flags)
        makes = values(camera_make)
        if makes:
            where.append(quoted("p.camera_make", makes))
            params.extend(makes)
        models = values(camera_model)
        if models:
            where.append(quoted("p.camera_model", models))
            params.extend(models)
        if date_from:
            where.append("date(p.taken) >= ?")
            params.append(date_from)
        if date_to:
            where.append("date(p.taken) <= ?")
            params.append(date_to)
        if min_score is not None:
            where.append("p.score >= ?")
            params.append(min_score)
        if score_max is not None:
            where.append("p.score <= ?")
            params.append(score_max)
        if sharpness_min is not None:
            where.append("COALESCE(m.sharpness_subject, m.sharpness) >= ?")
            params.append(sharpness_min)
        if aesthetic_min is not None:
            where.append("m.aesthetic >= ?")
            params.append(aesthetic_min)
        if subject_min is not None:
            where.append("m.subject_score >= ?")
            params.append(subject_min)
        if search:
            where.append("(l.relative_path LIKE ? OR r.path LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if selected_run:
            where.append(
                "EXISTS (SELECT 1 FROM selections s WHERE s.photo_id = p.id AND s.run_id = ?)"
            )
            params.append(selected_run)
        return where, params

    def count_photos(
        self,
        *,
        rating: int | Sequence[int] | None = None,
        event_id: int | Sequence[int] | None = None,
        group_id: int | Sequence[int] | None = None,
        label: str | Sequence[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float | None = None,
        search: str | None = None,
        selected_run: str | None = None,
        blur: str | Sequence[str] | None = None,
        flags: str | Sequence[str] | None = None,
        camera_make: str | Sequence[str] | None = None,
        camera_model: str | Sequence[str] | None = None,
        score_max: float | None = None,
        sharpness_min: float | None = None,
        aesthetic_min: float | None = None,
        subject_min: float | None = None,
        root: str | Sequence[str] | None = None,
        folder: str | Sequence[str] | None = None,
    ) -> int:
        """Count available locations matching the GUI/CLI filters."""
        where, params = self._photo_filters(
            rating=rating,
            event_id=event_id,
            group_id=group_id,
            label=label,
            date_from=date_from,
            date_to=date_to,
            min_score=min_score,
            search=search,
            selected_run=selected_run,
            blur=blur,
            flags=flags,
            camera_make=camera_make,
            camera_model=camera_model,
            score_max=score_max,
            sharpness_min=sharpness_min,
            aesthetic_min=aesthetic_min,
            subject_min=subject_min,
            root=root,
            folder=folder,
        )
        sql = f"SELECT COUNT(*) AS n {self._location_from()} WHERE " + " AND ".join(where)
        return int(self.connection.execute(sql, params).fetchone()["n"])

    def _location_from(self) -> str:
        """Shared FROM clause for location-level filters."""
        return (
            "FROM photo_locations l "
            "JOIN photos p ON p.id = l.photo_id "
            "JOIN roots r ON r.id = l.root_id "
            "LEFT JOIN metrics m ON m.photo_id = p.id"
        )

    def list_photos(
        self,
        *,
        rating: int | Sequence[int] | None = None,
        event_id: int | Sequence[int] | None = None,
        group_id: int | Sequence[int] | None = None,
        label: str | Sequence[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float | None = None,
        search: str | None = None,
        selected_run: str | None = None,
        blur: str | Sequence[str] | None = None,
        flags: str | Sequence[str] | None = None,
        camera_make: str | Sequence[str] | None = None,
        camera_model: str | Sequence[str] | None = None,
        score_max: float | None = None,
        sharpness_min: float | None = None,
        aesthetic_min: float | None = None,
        subject_min: float | None = None,
        root: str | Sequence[str] | None = None,
        folder: str | Sequence[str] | None = None,
        sort: str = "taken",
        order: str = "asc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Photo]:
        """Filtered location listing for the CLI and GUI."""
        where, params = self._photo_filters(
            rating=rating,
            event_id=event_id,
            group_id=group_id,
            label=label,
            date_from=date_from,
            date_to=date_to,
            min_score=min_score,
            search=search,
            selected_run=selected_run,
            blur=blur,
            flags=flags,
            camera_make=camera_make,
            camera_model=camera_model,
            score_max=score_max,
            sharpness_min=sharpness_min,
            aesthetic_min=aesthetic_min,
            subject_min=subject_min,
            root=root,
            folder=folder,
        )
        direction = "ASC" if order.lower().startswith("asc") else "DESC"
        columns = {
            "taken": ("p.taken", ["r.path", "l.relative_path"]),
            "path": ("l.relative_path", ["r.path"]),
            "score": ("p.score", ["p.taken", "r.path", "l.relative_path"]),
            "rating": ("p.rating", ["p.score", "p.taken"]),
            "sharpness": (
                "COALESCE(m.sharpness_subject, m.sharpness)",
                ["p.taken", "l.relative_path"],
            ),
            "bokeh": ("m.bokeh", ["p.taken", "l.relative_path"]),
            "aesthetic": ("m.aesthetic", ["p.taken", "l.relative_path"]),
            "subject": ("m.subject_score", ["p.taken", "l.relative_path"]),
        }
        key, tie_breakers = columns.get(sort, columns["taken"])
        order_by = ", ".join([f"{key} {direction}", *tie_breakers])
        sql = _LOCATION_SELECT
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_photo(row) for row in rows]

    def photo_ids(
        self,
        *,
        rating: int | Sequence[int] | None = None,
        event_id: int | Sequence[int] | None = None,
        group_id: int | Sequence[int] | None = None,
        label: str | Sequence[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float | None = None,
        search: str | None = None,
        blur: str | Sequence[str] | None = None,
        flags: str | Sequence[str] | None = None,
        camera_make: str | Sequence[str] | None = None,
        camera_model: str | Sequence[str] | None = None,
        score_max: float | None = None,
        sharpness_min: float | None = None,
        aesthetic_min: float | None = None,
        subject_min: float | None = None,
        root: str | Sequence[str] | None = None,
        folder: str | Sequence[str] | None = None,
    ) -> list[int]:
        """All location ids matching the filters, regardless of pagination."""
        where, params = self._photo_filters(
            rating=rating,
            event_id=event_id,
            group_id=group_id,
            label=label,
            date_from=date_from,
            date_to=date_to,
            min_score=min_score,
            search=search,
            blur=blur,
            flags=flags,
            camera_make=camera_make,
            camera_model=camera_model,
            score_max=score_max,
            sharpness_min=sharpness_min,
            aesthetic_min=aesthetic_min,
            subject_min=subject_min,
            root=root,
            folder=folder,
        )
        sql = "SELECT l.id AS id " + self._location_from()
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.path, l.relative_path"
        return [int(row["id"]) for row in self.connection.execute(sql, params).fetchall()]

    def folder_counts(
        self,
        *,
        rating: int | Sequence[int] | None = None,
        event_id: int | Sequence[int] | None = None,
        group_id: int | Sequence[int] | None = None,
        label: str | Sequence[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float | None = None,
        search: str | None = None,
        blur: str | Sequence[str] | None = None,
        flags: str | Sequence[str] | None = None,
        camera_make: str | Sequence[str] | None = None,
        camera_model: str | Sequence[str] | None = None,
        score_max: float | None = None,
        sharpness_min: float | None = None,
        aesthetic_min: float | None = None,
        subject_min: float | None = None,
        root: str | Sequence[str] | None = None,
        folder: str | Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Matching photo counts per folder, including ancestor folders."""
        where, params = self._photo_filters(
            rating=rating,
            event_id=event_id,
            group_id=group_id,
            label=label,
            date_from=date_from,
            date_to=date_to,
            min_score=min_score,
            search=search,
            blur=blur,
            flags=flags,
            camera_make=camera_make,
            camera_model=camera_model,
            score_max=score_max,
            sharpness_min=sharpness_min,
            aesthetic_min=aesthetic_min,
            subject_min=subject_min,
            root=root,
            folder=folder,
        )
        sql = (
            "SELECT r.path AS root_path, l.relative_path AS path "
            + self._location_from()
            + " WHERE "
            + " AND ".join(where)
        )
        counts: dict[tuple[str, str], int] = {}
        for row in self.connection.execute(sql, params):
            root_path = row["root_path"]
            relative = row["path"]
            parts = relative.split("/")
            folders = {"."}
            for index in range(1, len(parts)):
                folders.add("/".join(parts[:index]))
            for folder in folders:
                key = (root_path, folder)
                counts[key] = counts.get(key, 0) + 1
        items: list[dict[str, Any]] = []
        for (root_path, folder), count in sorted(counts.items()):
            label = Path(root_path).name if folder == "." else folder
            items.append({"root": root_path, "folder": folder, "label": label, "count": count})
        return items

    def filter_options(self) -> dict[str, list[Any]]:
        """Distinct values available for the multi-select filter controls."""
        makes = [
            row["value"]
            for row in self.connection.execute(
                "SELECT DISTINCT camera_make AS value FROM photos "
                "WHERE camera_make IS NOT NULL AND camera_make != '' ORDER BY value"
            )
        ]
        models = [
            row["value"]
            for row in self.connection.execute(
                "SELECT DISTINCT camera_model AS value FROM photos "
                "WHERE camera_model IS NOT NULL AND camera_model != '' ORDER BY value"
            )
        ]
        return {"camera_make": makes, "camera_model": models}

    def group_options(self) -> list[dict[str, Any]]:
        """Similarity groups with their member counts, for the group filter."""
        rows = self.connection.execute(
            "SELECT g.id, g.member_count FROM groups g ORDER BY g.id"
        ).fetchall()
        return [{"id": int(row["id"]), "count": int(row["member_count"])} for row in rows]

    def label_options(self) -> list[dict[str, Any]]:
        """Detection labels with their photo counts, for the label filter."""
        rows = self.connection.execute(
            "SELECT label, COUNT(DISTINCT photo_id) AS n FROM detections "
            "GROUP BY label ORDER BY n DESC, label"
        ).fetchall()
        return [{"label": row["label"], "count": int(row["n"])} for row in rows]

    def update_scores(self, entries: Iterable[tuple[int, float, int, str]]) -> None:
        """Update score, rating and flags for many photos."""
        with self.connection:
            self.connection.executemany(
                "UPDATE photos SET score = ?, rating = ?, flags = ? WHERE id = ?",
                [
                    (score, rating, json.dumps(flags), photo_id)
                    for photo_id, score, rating, flags in entries
                ],
            )

    def update_sharpness(self, entries: Iterable[tuple[int, float, float]]) -> None:
        """Update corpus-normalized global and subject sharpness for many photos."""
        with self.connection:
            self.connection.executemany(
                "UPDATE metrics SET sharpness = ?, sharpness_subject = ? WHERE photo_id = ?",
                [
                    (global_value, subject_value, photo_id)
                    for photo_id, global_value, subject_value in entries
                ],
            )

    def update_subject_metrics(self, entries: Iterable[tuple[int, float, float, float]]) -> None:
        """Update subject score and rarity for many photos."""
        with self.connection:
            self.connection.executemany(
                "UPDATE metrics SET subject_score = ?, subject_rarity = ? WHERE photo_id = ?",
                [(score, rarity, photo_id) for photo_id, score, rarity, _source in entries],
            )

    # ----------------------------------------------------------- groups/events

    def set_groups(
        self,
        assignments: Sequence[tuple[int, int]],
        *,
        method: str = "similarity",
        version: str = "1.0.0",
    ) -> dict[int, int]:
        """Replace all group assignments and return the mapping."""
        if not assignments:
            return {}
        counts: dict[int, int] = {}
        for _, group_id in assignments:
            counts[group_id] = counts.get(group_id, 0) + 1
        with self.connection:
            self.connection.execute("DELETE FROM photo_groups")
            self.connection.execute("DELETE FROM groups")
            self.connection.execute("UPDATE photos SET group_id = NULL")
            now = _iso(utcnow())
            for group_id, count in sorted(counts.items()):
                self.connection.execute(
                    "INSERT INTO groups (id, method, version, member_count, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (group_id, method, version, count, now),
                )
            self.connection.executemany(
                "INSERT INTO photo_groups (photo_id, group_id) VALUES (?, ?)", assignments
            )
            self.connection.executemany(
                "UPDATE photos SET group_id = ? WHERE id = ?",
                [(group_id, photo_id) for photo_id, group_id in assignments],
            )
        return dict(assignments)

    def assign_events(self, assignments: Sequence[tuple[int, int]]) -> None:
        """Replace photo-to-event assignments without touching the event rows."""
        with self.connection:
            self.connection.execute("DELETE FROM photo_events")
            self.connection.executemany(
                "INSERT INTO photo_events (photo_id, event_id) VALUES (?, ?)", assignments
            )
            self.connection.executemany(
                "UPDATE photos SET event_id = ? WHERE id = ?",
                [(event_id, photo_id) for photo_id, event_id in assignments],
            )

    def set_events(
        self, events: Sequence[Event], assignments: Sequence[tuple[int, int]]
    ) -> list[Event]:
        """Replace all events and their photo assignments."""
        now = _iso(utcnow())
        with self.connection:
            self.connection.execute("DELETE FROM photo_events")
            self.connection.execute("DELETE FROM events")
            self.connection.execute("UPDATE photos SET event_id = NULL")
            stored: list[Event] = []
            for event in events:
                cursor = self.connection.execute(
                    'INSERT INTO events (id, start, "end", label, source, photo_count, created_at) '
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.id,
                        _iso(event.start),
                        _iso(event.end),
                        event.label,
                        event.source,
                        event.photo_count,
                        now,
                    ),
                )
                event.id = int(cursor.lastrowid)
                stored.append(event)
            self.connection.execute(
                "UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX(id), 0) FROM events) "
                "WHERE name = 'events'"
            )
        if assignments:
            self.assign_events(assignments)
        return stored

    def events(self) -> list[Event]:
        rows = self.connection.execute(
            'SELECT id, start, "end", label, source, photo_count FROM events ORDER BY start, id'
        ).fetchall()
        return [
            Event(
                id=int(row["id"]),
                start=_parse_dt(row["start"]),
                end=_parse_dt(row["end"]),
                label=row["label"],
                source=row["source"],
                photo_count=int(row["photo_count"] or 0),
            )
            for row in rows
        ]

    # --------------------------------------------------------------- runs/selections

    def save_run(self, run: Run) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO runs (id, command, started_at, finished_at, status, config_hash,
                                  model_hashes, counts, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    finished_at=excluded.finished_at,
                    status=excluded.status,
                    config_hash=excluded.config_hash,
                    model_hashes=excluded.model_hashes,
                    counts=excluded.counts
                """,
                (
                    run.id,
                    run.command,
                    _iso(run.started_at),
                    _iso(run.finished_at),
                    run.status.value,
                    run.config_hash,
                    json.dumps(run.model_hashes, sort_keys=True),
                    json.dumps(run.counts, sort_keys=True),
                    _iso(utcnow()),
                ),
            )

    def finish_run(self, run: Run) -> None:
        run.finished_at = utcnow()
        self.save_run(run)

    def get_run(self, run_id: str) -> Run | None:
        row = self.connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        return Run(
            id=row["id"],
            command=row["command"],
            started_at=_parse_dt(row["started_at"]) or utcnow(),
            finished_at=_parse_dt(row["finished_at"]),
            status=RunStatus(row["status"]),
            config_hash=row["config_hash"],
            model_hashes=json.loads(row["model_hashes"] or "{}"),
            counts=json.loads(row["counts"] or "{}"),
        )

    def latest_run(self) -> Run | None:
        row = self.connection.execute(
            "SELECT id FROM runs ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return self.get_run(row["id"]) if row else None

    def latest_selection_run(self) -> Run | None:
        """Return the newest run that actually stored a selection."""
        row = self.connection.execute(
            """
            SELECT r.id
            FROM runs r
            JOIN selections s ON s.run_id = r.id
            GROUP BY r.id
            ORDER BY MAX(r.started_at) DESC, r.id DESC
            LIMIT 1
            """
        ).fetchone()
        return self.get_run(row["id"]) if row else None

    def set_selection(self, run_id: str, selections: Sequence[Selection]) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM selections WHERE run_id = ?", (run_id,))
            self.connection.executemany(
                "INSERT INTO selections (run_id, photo_id, rank, score, reason, quota_rule) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(run_id, s.photo_id, s.rank, s.score, s.reason, s.quota_rule) for s in selections],
            )

    def get_selection(self, run_id: str) -> list[Photo]:
        rows = self.connection.execute(
            """
            SELECT p.*,
                   m.sharpness, m.sharpness_raw, m.sharpness_subject, m.sharpness_subject_raw,
                   m.bokeh, m.blur_kind, m.blur_confidence, m.blur_score,
                   m.composition, m.composition_components, m.aesthetic, m.aesthetic_source,
                   m.subject_score, m.subject_rarity, m.exposure, s.rank, s.reason, s.quota_rule,
                   (SELECT l.id FROM photo_locations l
                    WHERE l.photo_id = p.id AND l.available = 1
                    ORDER BY l.relative_path LIMIT 1) AS location_id,
                   (SELECT l.root_id FROM photo_locations l
                    WHERE l.photo_id = p.id AND l.available = 1
                    ORDER BY l.relative_path LIMIT 1) AS root_id,
                   (SELECT l.relative_path FROM photo_locations l
                    WHERE l.photo_id = p.id AND l.available = 1
                    ORDER BY l.relative_path LIMIT 1) AS path,
                   (SELECT r.path FROM photo_locations l
                    JOIN roots r ON r.id = l.root_id
                    WHERE l.photo_id = p.id AND l.available = 1
                    ORDER BY l.relative_path LIMIT 1) AS root_path,
                   (SELECT l.available FROM photo_locations l
                    WHERE l.photo_id = p.id AND l.available = 1
                    ORDER BY l.relative_path LIMIT 1) AS available
            FROM selections s
            JOIN photos p ON p.id = s.photo_id
            LEFT JOIN metrics m ON m.photo_id = p.id
            WHERE s.run_id = ?
            ORDER BY s.rank
            """,
            (run_id,),
        ).fetchall()
        photos = []
        for row in rows:
            photo = self._row_to_photo(row)
            photo.selected = True
            photo.reason = row["reason"] if "reason" in row.keys() else ""
            photo.quota_rule = row["quota_rule"] if "quota_rule" in row.keys() else ""
            photos.append(photo)
        return photos

    # ------------------------------------------------------------- overrides/jobs

    def set_override(
        self,
        photo_id: int,
        *,
        rating: int | None = None,
        keep: bool | None = None,
        source: OverrideSource = OverrideSource.CLI,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO overrides (photo_id, rating, keep, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(photo_id) DO UPDATE SET
                    rating=excluded.rating,
                    keep=excluded.keep,
                    source=excluded.source,
                    created_at=excluded.created_at
                """,
                (
                    photo_id,
                    rating,
                    None if keep is None else int(keep),
                    source.value,
                    _iso(utcnow()),
                ),
            )

    def get_overrides(self) -> list[Override]:
        rows = self.connection.execute(
            "SELECT photo_id, rating, keep, source, created_at FROM overrides"
        ).fetchall()
        return [
            Override(
                photo_id=int(row["photo_id"]),
                rating=row["rating"],
                keep=None if row["keep"] is None else bool(row["keep"]),
                source=OverrideSource(row["source"]),
                created_at=_parse_dt(row["created_at"]),
            )
            for row in rows
        ]

    def create_job(self, kind: str, payload: dict[str, Any]) -> int:
        now = _iso(utcnow())
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO jobs (kind, status, payload, progress, created_at, updated_at) "
                "VALUES (?, 'pending', ?, 0, ?, ?)",
                (kind, json.dumps(payload, sort_keys=True), now, now),
            )
        return int(cursor.lastrowid)

    def update_job(
        self, job_id: int, *, status: str, progress: float | None = None, result: Any = None
    ) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE jobs SET status = ?, progress = COALESCE(?, progress), "
                "result = COALESCE(?, result), updated_at = ? WHERE id = ?",
                (
                    status,
                    progress,
                    json.dumps(result, sort_keys=True) if result is not None else None,
                    _iso(utcnow()),
                    job_id,
                ),
            )

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "payload": json.loads(row["payload"] or "{}"),
            "progress": row["progress"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        return [
            self.get_job(int(row["id"])) or {}
            for row in self.connection.execute("SELECT id FROM jobs ORDER BY id DESC")
        ]


def open_repository(db_path: str | Path) -> Repository:
    """Convenience wrapper around :meth:`Repository.open`."""
    return Repository.open(db_path)
