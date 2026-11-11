"""``image-triage scan``: list images and their metadata."""

from __future__ import annotations

from pathlib import Path

import typer

from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json, print_table
from image_triage.core.errors import InputError
from image_triage.io.scan import find_images, scan_file


def scan(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Photo library root."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Recursively find images and print capture time, dimensions and GPS presence."""
    overrides = {"input": {"root": input_dir}} if input_dir is not None else None
    settings = get_settings(ctx, config, overrides)
    root = Path(settings.input.root).expanduser().resolve()
    if not root.is_dir():
        raise InputError(f"input folder not found: {root}", path=str(root))
    exclude = tuple(root / name for name in settings.input.exclude) + (root / ".image-triage",)
    paths = find_images(root, exclude)

    records = []
    errors = []
    for path in paths:
        try:
            info = scan_file(path)
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "taken": info.taken.isoformat(),
                    "width": info.width,
                    "height": info.height,
                    "camera": [info.camera_make, info.camera_model]
                    if info.camera_make or info.camera_model
                    else None,
                    "has_gps": info.gps_lat is not None,
                }
            )
        except Exception as exc:
            errors.append({"path": path.relative_to(root).as_posix(), "error": str(exc)})

    if json_output:
        emit_json(
            {
                "input": str(root),
                "count": len(records),
                "errors": errors,
                "photos": records,
            }
        )
    else:
        print_table(
            [
                {
                    "path": record["path"],
                    "taken": record["taken"],
                    "size": f"{record['width']}x{record['height']}",
                    "gps": "yes" if record["has_gps"] else "no",
                }
                for record in records
            ],
            ["path", "taken", "size", "gps"],
        )
        if errors:
            typer.echo(f"{len(errors)} file(s) could not be read", err=True)
