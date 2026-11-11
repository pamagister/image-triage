"""Versioned JSON report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from image_triage import __version__
from image_triage.core.models import SELECTION_VERSION, Photo, Run
from image_triage.core.settings import Settings
from image_triage.scoring.score import score_breakdown

REPORT_SCHEMA_VERSION = "1.0.0"


def build_report(
    photos: list[Photo],
    selected: list[Photo],
    settings: Settings,
    run: Run | None,
    *,
    include_gps: bool | None = None,
) -> dict[str, Any]:
    """Build the stable, GPS-safe JSON report document."""
    selected_by_id = {photo.id: photo for photo in selected if photo.id is not None}
    records = []
    for photo in sorted(photos, key=lambda item: (item.taken or item.path, item.path)):
        record = photo.to_dict(
            include_gps=bool(settings.report.include_gps if include_gps is None else include_gps)
        )
        record["score_breakdown"] = score_breakdown(photo, settings)
        chosen = selected_by_id.get(photo.id)
        record["selected"] = chosen is not None
        if chosen is not None:
            record["reason"] = chosen.reason
            record["quota_rule"] = chosen.quota_rule
        records.append(record)

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool_version": __version__,
        "run": {
            "id": run.id,
            "command": run.command,
            "status": run.status.value,
            "config_hash": run.config_hash,
            "model_hashes": run.model_hashes,
            "counts": run.counts,
        }
        if run
        else None,
        "config_hash": settings.fingerprint(),
        "model_hashes": settings.model_hashes(),
        "selection_version": SELECTION_VERSION,
        "counts": {
            "photos": len(photos),
            "selected": len(selected_by_id),
            "groups": len({photo.group_id for photo in photos if photo.group_id is not None}),
            "events": len({photo.event_id for photo in photos if photo.event_id is not None}),
        },
        "photos": records,
    }


def write_report(report: dict[str, Any], path: Path) -> Path:
    """Write a report as UTF-8 JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return path
