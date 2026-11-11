"""``image-triage plan``: write a reviewable selection plan."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from image_triage.analysis.pipeline import selection_run_id
from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json
from image_triage.core.models import Run, RunStatus, Selection
from image_triage.db.repository import Repository
from image_triage.grouping.build import build_groups_and_events
from image_triage.scoring.score import score_library
from image_triage.selection.profiles import load_profile
from image_triage.selection.select import select_photos


def plan(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    output: Path = typer.Option(Path("plan.json"), "--output", help="Plan JSON file."),
    top_n: int | None = typer.Option(None, "--top-n", help="Maximum selected photos."),
    profile_name: str | None = typer.Option(None, "--profile", help="Selection profile."),
    json_output: bool = typer.Option(False, "--json", help="Also print the plan as JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Compute a selection and write it as reviewable JSON without exporting."""
    overrides: dict[str, Any] = {}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)
    repository = Repository.open(settings.database_path)
    try:
        photos = build_groups_and_events(repository, settings)
        photos = score_library(repository, settings)
        profile = load_profile(
            settings,
            profile_name,
            {"top_n": top_n} if top_n is not None else None,
        )
        selected = select_photos(photos, profile)
        run_id = selection_run_id(settings, photos, profile)
        run = Run(
            id=run_id,
            command="plan",
            started_at=datetime.now(UTC),
            status=RunStatus.COMPLETED,
            config_hash=settings.fingerprint(),
            model_hashes=settings.model_hashes(),
            counts={"total": len(photos), "selected": len(selected)},
        )
        repository.save_run(run)
        repository.set_selection(
            run_id,
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
        "schema_version": "1.0.0",
        "run_id": run_id,
        "profile": profile.to_dict(),
        "selections": [
            {
                "photo_id": item.photo.id,
                "path": item.photo.path,
                "rank": item.rank,
                "score": round(item.score, 6),
                "rating": item.photo.rating,
                "reason": item.reason,
                "quota_rule": item.quota_rule,
            }
            for item in selected
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if json_output:
        emit_json(payload)
    else:
        typer.echo(f"wrote {len(selected)} selections to {output}")
