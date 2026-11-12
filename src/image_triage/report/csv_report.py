"""Stable CSV report generation."""

from __future__ import annotations

import csv
from pathlib import Path

from image_triage.core.models import Photo

BASE_COLUMNS = [
    "id",
    "path",
    "taken",
    "width",
    "height",
    "score",
    "rating",
    "group_id",
    "event_id",
    "sharpness",
    "sharpness_subject",
    "bokeh",
    "blur_kind",
    "blur_confidence",
    "composition",
    "aesthetic",
    "subject_score",
    "subject_rarity",
    "selected",
    "reason",
]


def _row(photo: Photo) -> dict[str, object]:
    return {
        "id": photo.id,
        "path": photo.path,
        "taken": photo.taken.isoformat() if photo.taken else "",
        "width": photo.width,
        "height": photo.height,
        "score": round(photo.score, 6),
        "rating": photo.rating,
        "group_id": photo.group_id,
        "event_id": photo.event_id,
        "sharpness": round(photo.metrics.sharpness, 6),
        "sharpness_subject": round(photo.metrics.sharpness_subject, 6),
        "bokeh": round(photo.metrics.bokeh, 6),
        "blur_kind": photo.metrics.blur_kind.value,
        "blur_confidence": round(photo.metrics.blur_confidence, 6),
        "composition": round(photo.metrics.composition, 6),
        "aesthetic": round(photo.metrics.aesthetic, 6),
        "subject_score": round(photo.metrics.subject_score, 6),
        "subject_rarity": round(photo.metrics.subject_rarity, 6),
        "selected": int(photo.selected),
        "reason": photo.reason,
    }


def write_csv(photos: list[Photo], path: Path, columns: list[str] | None = None) -> Path:
    """Write one row per photo, sorted by capture time then path."""
    columns = columns or BASE_COLUMNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for photo in sorted(photos, key=lambda item: (item.taken or item.path, item.path)):
            row = _row(photo)
            writer.writerow({column: row.get(column, "") for column in columns})
    return path
