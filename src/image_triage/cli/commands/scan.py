"""``image-triage scan``: list images and their metadata."""

from __future__ import annotations

from pathlib import Path

import typer

from image_triage.analysis.analyze import scan_plan
from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json, print_table
from image_triage.io.scan import scan_file


def scan(
    ctx: typer.Context,
    root: Path | None = typer.Option(
        None, "--root", "--input", help="Restrict the listing to one watched root."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Recursively find images and print capture time, dimensions and GPS presence."""
    overrides = {"input": {"roots": [root]}} if root is not None else None
    settings = get_settings(ctx, config, overrides)
    plan = scan_plan(settings)

    records = []
    errors = []
    for library_root, paths in plan:
        if not paths and not records:
            continue
        for path in paths:
            relative = path.relative_to(library_root).as_posix()
            try:
                info = scan_file(path)
                records.append(
                    {
                        "root": str(library_root),
                        "path": relative,
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
                errors.append({"root": str(library_root), "path": relative, "error": str(exc)})

    if json_output:
        emit_json(
            {
                "roots": [str(item[0]) for item in plan],
                "count": len(records),
                "errors": errors,
                "photos": records,
            }
        )
    else:
        print_table(
            [
                {
                    "path": f"{record['root']}/{record['path']}",
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
