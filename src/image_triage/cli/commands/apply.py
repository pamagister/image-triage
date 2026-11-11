"""``image-triage apply``: export the photos listed in a selection plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json
from image_triage.core.errors import InputError
from image_triage.core.models import ExportMode
from image_triage.db.repository import Repository
from image_triage.export.export import export_photos


def _plan_paths(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read plan {path}: {exc}", path=str(path)) from exc
    entries = payload.get("selections") or payload.get("paths") or []
    paths = []
    for entry in entries:
        if isinstance(entry, str):
            paths.append(entry)
        elif isinstance(entry, dict) and entry.get("path"):
            paths.append(str(entry["path"]))
    return paths


def apply(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    plan_file: Path | None = typer.Option(None, "--plan", help="Selection plan JSON."),
    output: Path | None = typer.Option(None, "--output", help="Export root."),
    mode: str | None = typer.Option(None, "--mode", help="copy, hardlink or symlink."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Read a plan and export its selected originals."""
    overrides: dict[str, Any] = {}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)
    if plan_file is None:
        raise InputError("--plan is required")
    paths = _plan_paths(plan_file)
    root = Path(settings.input.root).expanduser().resolve()
    repository = Repository.open(settings.database_path)
    try:
        photos = []
        for relative in paths:
            photo = repository.photo_by_path(relative)
            if photo is None:
                raise InputError(f"photo not in database: {relative}")
            photos.append(photo)
    finally:
        repository.close()

    target = output or Path("selected")
    exported = export_photos(photos, root, target, ExportMode(mode or settings.report.export_mode))
    if json_output:
        emit_json(
            {
                "plan": str(plan_file),
                "output": str(target),
                "mode": (mode or settings.report.export_mode),
                "exported": [str(path) for path in exported],
            }
        )
    else:
        typer.echo(f"exported {len(exported)} photos to {target}")
