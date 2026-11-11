"""``image-triage analyze``: run the per-photo analysis pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from image_triage.analysis.analyze import analyze_library
from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json, emit_ndjson
from image_triage.db.repository import Repository


def analyze(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON summary."),
    ndjson: bool = typer.Option(False, "--ndjson", help="Emit progress as NDJSON."),
    strict: bool = typer.Option(False, "--strict", help="Fail on per-file analysis errors."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Analyze sharpness, blur, composition, subjects and aesthetics for every photo."""
    overrides: dict[str, Any] = {"app": {"strict": strict}}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)

    progress = None
    if ndjson:
        progress = emit_ndjson

    repository = Repository.open(settings.database_path)
    try:
        result = analyze_library(
            settings, repository, progress=progress, strict=strict or settings.app.strict
        )
    finally:
        repository.close()

    if json_output:
        emit_json(result.to_dict())
    else:
        typer.echo(
            f"analyzed {result.analyzed}, reused {result.reused}, "
            f"errors {len(result.errors)}, total {result.total}"
        )
