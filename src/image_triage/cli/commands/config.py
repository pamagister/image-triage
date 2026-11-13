"""``image-triage config``: initialize, show and validate configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml

from image_triage.cli.output import emit_json
from image_triage.core.settings import Settings

config_app = typer.Typer(help="Manage the YAML configuration.", no_args_is_help=True)


def _default_settings() -> Settings:
    """Default settings without reading the ambient YAML file or environment."""
    return Settings.model_validate({})


def _dump(settings: Settings) -> str:
    payload = settings.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


@config_app.command("init")
def init(
    output: Path = typer.Option(Path("image-triage.yaml"), "--output", help="Config file."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    """Write a documented default configuration file."""
    if output.exists() and not force:
        typer.echo(f"{output} already exists; use --force to overwrite")
        raise typer.Exit(2)
    output.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# image-triage configuration\n"
        "# Precedence: CLI options > IMAGE_TRIAGE_* environment variables > this file > defaults.\n"
    )
    output.write_text(header + _dump(_default_settings()), encoding="utf-8")
    typer.echo(f"wrote default configuration to {output}")


@config_app.command("show")
def show(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Print the effective merged configuration."""
    settings = _load(config)
    if json_output:
        emit_json(settings.model_dump(mode="json"))
    else:
        typer.echo(_dump(settings))


def _load(config: Path | None) -> Settings:
    from image_triage.core.settings import load_settings

    return load_settings(config)


@config_app.command("validate")
def validate(
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Validate weights, paths, profiles and model files."""
    settings = _load(config)
    checks: list[dict[str, Any]] = []
    weights = (
        settings.scoring.sharpness_weight
        + settings.scoring.composition_weight
        + settings.scoring.aesthetic_weight
        + settings.scoring.subject_weight
    )
    checks.append({"name": "weights", "ok": weights > 0, "detail": {"sum": weights}})
    roots = settings.watched_roots
    checks.append(
        {
            "name": "input",
            "ok": all(path.is_dir() for path in roots),
            "detail": {"roots": [str(path) for path in roots]},
        }
    )
    for name, path in (
        ("yolo", settings.models.yolo_path),
        ("aesthetic", settings.models.aesthetic_path),
    ):
        checks.append(
            {
                "name": f"model:{name}",
                "ok": path.is_file() or not settings.models.enabled,
                "detail": {"path": str(path), "installed": path.is_file()},
            }
        )

    from image_triage.selection.profiles import load_profile

    try:
        profile = load_profile(settings)
        checks.append({"name": "profile", "ok": True, "detail": profile.to_dict()})
    except Exception as exc:
        checks.append({"name": "profile", "ok": False, "detail": {"error": str(exc)}})

    ok = all(check["ok"] for check in checks)
    if json_output:
        emit_json({"ok": ok, "checks": checks})
    else:
        for check in checks:
            typer.echo(f"{'ok  ' if check['ok'] else 'FAIL'} {check['name']}: {check['detail']}")
    if not ok:
        raise typer.Exit(2)
