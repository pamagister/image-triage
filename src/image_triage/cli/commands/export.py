"""``image-triage export``: export the latest selection or a saved plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json
from image_triage.core.errors import InputError
from image_triage.core.models import ExportMode, Photo
from image_triage.db.repository import Repository
from image_triage.export.export import export_photos


def _selected_photos(repository: Repository, run_id: str | None) -> list[Photo]:
    run = repository.get_run(run_id) if run_id else repository.latest_run()
    if run is not None:
        photos = repository.get_selection(run.id)
        if photos:
            return photos
    return [photo for photo in repository.all_photos() if photo.selected]


def export(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    output: Path = typer.Option(Path("selected"), "--output", help="Export root."),
    mode: str | None = typer.Option(None, "--mode", help="copy, hardlink or symlink."),
    run_id: str | None = typer.Option(None, "--run-id", help="Selection run id."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Export selected originals, preserving their paths relative to the input root."""
    overrides: dict[str, Any] = {}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)
    root = Path(settings.input.root).expanduser().resolve()
    repository = Repository.open(settings.database_path)
    try:
        photos = _selected_photos(repository, run_id)
    finally:
        repository.close()
    if not photos:
        raise InputError("no selection found; run select or run first")
    exported = export_photos(photos, root, output, ExportMode(mode or settings.report.export_mode))
    if json_output:
        emit_json(
            {
                "input": str(root),
                "output": str(output),
                "mode": mode or settings.report.export_mode,
                "count": len(exported),
                "files": [str(path) for path in exported],
            }
        )
    else:
        typer.echo(f"exported {len(exported)} photos to {output}")
