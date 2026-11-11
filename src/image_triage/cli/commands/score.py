"""``image-triage score``: compute quality scores and star ratings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json, print_table
from image_triage.core.models import SCORING_VERSION
from image_triage.db.repository import Repository
from image_triage.grouping.build import build_groups_and_events
from image_triage.scoring.score import score_library


def score(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Group, detect events, score and rate all analyzed photos."""
    overrides: dict[str, Any] = {}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)
    repository = Repository.open(settings.database_path)
    try:
        photos = build_groups_and_events(repository, settings)
        photos = score_library(repository, settings)
    finally:
        repository.close()

    ranked = sorted(
        photos,
        key=lambda photo: (-photo.score, photo.taken or photo.path, photo.path),
    )
    summary = {
        "formula_version": SCORING_VERSION,
        "weights": {
            "sharpness": settings.scoring.sharpness_weight,
            "composition": settings.scoring.composition_weight,
            "aesthetic": settings.scoring.aesthetic_weight,
            "subject": settings.scoring.subject_weight,
        },
        "count": len(photos),
        "groups": len({photo.group_id for photo in photos}),
        "events": len({photo.event_id for photo in photos}),
        "top": [
            {
                "path": photo.path,
                "score": round(photo.score, 4),
                "rating": photo.rating,
                "group": photo.group_id,
                "event": photo.event_id,
            }
            for photo in ranked[:10]
        ],
    }
    if json_output:
        emit_json(summary)
    else:
        print_table(
            [
                {
                    "path": item["path"],
                    "score": item["score"],
                    "rating": item["rating"],
                    "group": item["group"],
                    "event": item["event"],
                }
                for item in summary["top"]
            ],
            ["path", "score", "rating", "group", "event"],
        )
