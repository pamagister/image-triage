"""``image-triage report``: write the JSON or CSV report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json
from image_triage.core.errors import InputError
from image_triage.db.repository import Repository
from image_triage.report.csv_report import write_csv
from image_triage.report.json_report import build_report, write_report


def _selected(repository: Repository, run_id: str | None):
    run = repository.get_run(run_id) if run_id else repository.latest_run()
    if run is not None:
        selected = repository.get_selection(run.id)
        if selected:
            return run, selected
    return run, [photo for photo in repository.all_photos() if photo.selected]


def report(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    output: Path | None = typer.Option(None, "--output", help="Report file."),
    report_format: str = typer.Option("json", "--format", help="json or csv."),
    run_id: str | None = typer.Option(None, "--run-id", help="Selection run id."),
    include_gps: bool = typer.Option(False, "--include-gps", help="Include GPS coordinates."),
    json_output: bool = typer.Option(False, "--json", help="Print the report to stdout."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Write a versioned JSON report or a stable CSV summary."""
    overrides: dict[str, Any] = {}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)
    repository = Repository.open(settings.database_path)
    try:
        run, selected = _selected(repository, run_id)
        photos = repository.all_photos()
    finally:
        repository.close()
    if not photos:
        raise InputError("database contains no analyzed photos")

    if report_format == "csv":
        target = output or Path("selection.csv")
        write_csv(photos, target, settings.report.csv_columns)
        if json_output:
            emit_json({"format": "csv", "output": str(target), "rows": len(photos)})
        else:
            typer.echo(f"wrote {len(photos)} rows to {target}")
        return

    document = build_report(photos, selected, settings, run, include_gps=include_gps)
    if json_output:
        emit_json(document)
        return
    target = output or Path("report.json")
    write_report(document, target)
    typer.echo(f"wrote report for {len(photos)} photos to {target}")
