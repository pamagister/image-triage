"""``image-triage models``: install and list analysis models."""

from __future__ import annotations

from pathlib import Path

import typer

from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json, print_table
from image_triage.models.registry import install_model, list_models

models_app = typer.Typer(help="Install and inspect ONNX models.", no_args_is_help=True)


@models_app.command("install")
def install(
    ctx: typer.Context,
    model: str = typer.Argument(..., help="yolo or aesthetic."),
    path: Path | None = typer.Option(None, "--path", help="Install from a local ONNX file."),
    sha256: str | None = typer.Option(None, "--sha256", help="Expected SHA256 for --path."),
    force: bool = typer.Option(False, "--force", help="Replace an existing model."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Install a model, verify its checksum and record its license."""
    settings = get_settings(ctx)
    entry = install_model(settings, model, path=path, sha256=sha256, force=force)
    if json_output:
        emit_json(entry)
    else:
        typer.echo(f"installed {model}: {entry['path']}")
        typer.echo(f"license: {entry['license']} {entry['license_url']}".rstrip())


@models_app.command("list")
def list_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List known models, installed paths and licenses."""
    settings = get_settings(ctx)
    entries = list_models(settings)
    if json_output:
        emit_json({"models": entries})
    else:
        print_table(
            [
                {
                    "model": entry["name"],
                    "installed": "yes" if entry["installed"] else "no",
                    "path": entry["path"],
                    "license": entry["license"],
                }
                for entry in entries
            ],
            ["model", "installed", "path", "license"],
        )
        for entry in entries:
            if not entry["installed"]:
                typer.echo(
                    f"  {entry['name']}: {entry['description']}",
                    err=True,
                )


def models(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show the model registry."""
    settings = get_settings(ctx)
    entries = list_models(settings)
    if json_output:
        emit_json({"models": entries})
    else:
        print_table(
            [
                {
                    "model": entry["name"],
                    "installed": "yes" if entry["installed"] else "no",
                    "path": entry["path"],
                    "license": entry["license"],
                }
                for entry in entries
            ],
            ["model", "installed", "path", "license"],
        )
