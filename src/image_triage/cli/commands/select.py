"""``image-triage select``: select the best N photos and persist the run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from image_triage.analysis.pipeline import selection_run_id
from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json, print_table
from image_triage.core.models import Run, RunStatus, Selection
from image_triage.db.repository import Repository
from image_triage.grouping.build import build_groups_and_events
from image_triage.scoring.score import score_library
from image_triage.selection.profiles import load_profile
from image_triage.selection.select import select_photos


def select(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    top_n: int | None = typer.Option(None, "--top-n", help="Maximum selected photos."),
    profile_name: str | None = typer.Option(None, "--profile", help="Selection profile."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Group, score and select photos using the active profile."""
    overrides: dict[str, Any] = {}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)
    repository = Repository.open(settings.database_path)
    try:
        photos = build_groups_and_events(repository, settings)
        photos = score_library(repository, settings)
        selection_overrides = {"top_n": top_n} if top_n is not None else None
        profile = load_profile(settings, profile_name, selection_overrides)
        selected = select_photos(photos, profile)
        run = Run(
            id=selection_run_id(settings, photos, profile),
            command="select",
            started_at=datetime.now(UTC),
            status=RunStatus.COMPLETED,
            config_hash=settings.fingerprint(),
            model_hashes=settings.model_hashes(),
            counts={"total": len(photos), "selected": len(selected)},
        )
        repository.save_run(run)
        repository.set_selection(
            run.id,
            [
                Selection(item.photo.id, item.rank, item.score, item.reason, item.quota_rule)
                for item in selected
                if item.photo.id is not None
            ],
        )
        repository.finish_run(run)
    finally:
        repository.close()

    payload = {
        "run_id": run.id,
        "profile": profile.to_dict(),
        "selected": [
            {
                "rank": item.rank,
                "path": item.photo.path,
                "score": round(item.score, 6),
                "rating": item.photo.rating,
                "reason": item.reason,
                "quota_rule": item.quota_rule,
            }
            for item in selected
        ],
    }
    if json_output:
        emit_json(payload)
    else:
        print_table(
            [
                {
                    "rank": item["rank"],
                    "path": item["path"],
                    "score": item["score"],
                    "rating": item["rating"],
                    "reason": item["reason"],
                }
                for item in payload["selected"]
            ],
            ["rank", "path", "score", "rating", "reason"],
        )
