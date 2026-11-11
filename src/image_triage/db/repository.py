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

    def upsert_photo(
        self,
        photo: Photo,
        *,
        metric_version: str = METRIC_VERSION,
        commit: bool = True,
    ) -> int:
        """Insert or update a photo with its metrics, detections and embedding."""
        now = utcnow()
        analyzed_at = photo.analyzed_at or now
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO photos (
                    path, digest, phash, taken, width, height, camera_make, camera_model,
                    gps_lat, gps_lon, event_id, group_id, score, rating, flags,
                    model_signature, analyzed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    digest=excluded.digest,
                    phash=excluded.phash,
                    taken=excluded.taken,
                    width=excluded.width,
                    height=excluded.height,
                    camera_make=excluded.camera_make,
                    camera_model=excluded.camera_model,
                    gps_lat=excluded.gps_lat,
                    gps_lon=excluded.gps_lon,
                    score=excluded.score,
                    rating=excluded.rating,
                    flags=excluded.flags,
                    model_signature=excluded.model_signature,
                    analyzed_at=excluded.analyzed_at
                RETURNING id
                """,
                (
                    photo.path,
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
            self.connection.execute(
                """
                INSERT INTO metrics (
                    photo_id, sharpness, sharpness_raw, blur_kind, blur_confidence, composition,
                    composition_components, aesthetic, aesthetic_source, subject_score,
                    subject_rarity, exposure, metric_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(photo_id) DO UPDATE SET
                    sharpness=excluded.sharpness,
                    sharpness_raw=excluded.sharpness_raw,
                    blur_kind=excluded.blur_kind,
                    blur_confidence=excluded.blur_confidence,
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
                    photo.metrics.blur_kind.value,
                    photo.metrics.blur_confidence,
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
        return photo.id

    def photo_by_path(self, path: str) -> Photo | None:
        row = self.connection.execute("SELECT id FROM photos WHERE path = ?", (path,)).fetchone()
        return self.photo_by_id(int(row["id"])) if row else None

    def photo_by_id(self, photo_id: int) -> Photo | None:
        row = self.connection.execute(
            """
            SELECT p.*, m.sharpness, m.sharpness_raw, m.blur_kind, m.blur_confidence,
                   m.composition, m.composition_components, m.aesthetic, m.aesthetic_source,
                   m.subject_score, m.subject_rarity, m.exposure
            FROM photos p
            LEFT JOIN metrics m ON m.photo_id = p.id
            WHERE p.id = ?
            """,
            (photo_id,),
        ).fetchone()
        return self._row_to_photo(row) if row else None

    def all_photos(self) -> list[Photo]:
        """Return every photo ordered by capture time and path."""
        rows = self.connection.execute(
            """
            SELECT p.*, m.sharpness, m.sharpness_raw, m.blur_kind, m.blur_confidence,
                   m.composition, m.composition_components, m.aesthetic, m.aesthetic_source,
                   m.subject_score, m.subject_rarity, m.exposure
            FROM photos p
            LEFT JOIN metrics m ON m.photo_id = p.id
            ORDER BY p.taken, p.path
            """
        ).fetchall()
        return [self._row_to_photo(row) for row in rows]

    def count_photos(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS n FROM photos").fetchone()
        return int(row["n"])

    def _row_to_photo(self, row: sqlite3.Row) -> Photo:
        flags = json.loads(row["flags"] or "[]")
        components = json.loads(row["composition_components"] or "{}")
        metrics = Metrics(
            sharpness=float(row["sharpness"] or 0.0),
            sharpness_raw=float(row["sharpness_raw"] or 0.0),
            blur_kind=BlurKind(row["blur_kind"] or "none"),
            blur_confidence=float(row["blur_confidence"] or 0.0),
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
        return Photo(
            id=int(row["id"]),
            path=row["path"],
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
        )

    def list_photos(
        self,
        *,
        rating: int | None = None,
        event_id: int | None = None,
        group_id: int | None = None,
        label: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float | None = None,
        search: str | None = None,
        selected_run: str | None = None,
        sort: str = "taken",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Photo]:
        """Filtered photo listing for the CLI and GUI."""
        where: list[str] = []
        params: list[Any] = []
        if rating is not None:
            where.append("p.rating = ?")
            params.append(rating)
        if event_id is not None:
            where.append("p.event_id = ?")
            params.append(event_id)
        if group_id is not None:
            where.append("p.group_id = ?")
            params.append(group_id)
        if label:
            where.append(
                "EXISTS (SELECT 1 FROM detections d WHERE d.photo_id = p.id AND d.label = ?)"
            )
            params.append(label)
        if date_from:
            where.append("p.taken >= ?")
            params.append(date_from)
        if date_to:
            where.append("p.taken <= ?")
            params.append(date_to)
        if min_score is not None:
            where.append("p.score >= ?")
            params.append(min_score)
        if search:
            where.append("p.path LIKE ?")
            params.append(f"%{search}%")
        if selected_run:
            where.append(
                "EXISTS (SELECT 1 FROM selections s WHERE s.photo_id = p.id AND s.run_id = ?)"
            )
            params.append(selected_run)
        order = {
            "taken": "p.taken, p.path",
            "path": "p.path",
            "score": "p.score DESC, p.taken, p.path",
            "rating": "p.rating DESC, p.score DESC, p.taken",
        }.get(sort, "p.taken, p.path")
        sql = """
            SELECT p.*, m.sharpness, m.sharpness_raw, m.blur_kind, m.blur_confidence,
                   m.composition, m.composition_components, m.aesthetic, m.aesthetic_source,
                   m.subject_score, m.subject_rarity, m.exposure
            FROM photos p
            LEFT JOIN metrics m ON m.photo_id = p.id
            """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_photo(row) for row in rows]

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

    def update_sharpness(self, entries: Iterable[tuple[int, float]]) -> None:
        """Update the corpus-normalized sharpness for many photos."""
        with self.connection:
            self.connection.executemany(
                "UPDATE metrics SET sharpness = ? WHERE photo_id = ?",
                [(value, photo_id) for photo_id, value in entries],
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
                    'INSERT INTO events (start, "end", label, source, photo_count, created_at) '
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
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
            SELECT p.*, m.sharpness, m.sharpness_raw, m.blur_kind, m.blur_confidence,
                   m.composition, m.composition_components, m.aesthetic, m.aesthetic_source,
                   m.subject_score, m.subject_rarity, m.exposure, s.rank, s.reason, s.quota_rule
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
