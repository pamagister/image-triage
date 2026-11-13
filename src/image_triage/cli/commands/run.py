"""``image-triage run``: the all-in-one triage pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from image_triage.analysis.pipeline import run_pipeline
from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json
from image_triage.db.repository import Repository


def run(
    ctx: typer.Context,
    root: Path | None = typer.Option(
        None, "--root", "--input", help="Restrict the run to one watched root."
    ),
    output: Path = typer.Option(Path("selected"), "--output", help="Output root."),
    top_n: int | None = typer.Option(None, "--top-n", help="Maximum selected photos."),
    profile_name: str | None = typer.Option(None, "--profile", help="Selection profile."),
    export: bool = typer.Option(True, "--export/--no-export", help="Export selected originals."),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON summary."),
    strict: bool = typer.Option(False, "--strict", help="Fail on per-file analysis errors."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Analyze, group, score, select, report and export in one deterministic pass."""
    overrides: dict[str, Any] = {"app": {"strict": strict}}
    if root is not None:
        overrides["input"] = {"roots": [root]}
    settings = get_settings(ctx, config, overrides)
    repository = Repository.open(settings.database_path)
    try:
        result = run_pipeline(
            settings,
            repository,
            output=output,
            top_n=top_n,
            profile_name=profile_name,
            export=export,
        )
    finally:
        repository.close()

    payload = result.to_dict()
    if json_output:
        emit_json(payload)
    else:
        typer.echo(
            f"run {result.run_id}: analyzed {result.analyzed}, reused {result.reused}, "
            f"selected {len(result.selected)} of {result.total}"
        )
        typer.echo(f"report: {result.report_path}")
        typer.echo(f"csv: {result.csv_path}")
        typer.echo(f"exported: {len(result.export_paths)}")
