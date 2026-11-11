"""Typer application entry point and shared CLI state."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer

from image_triage.cli.output import emit_error
from image_triage.core.errors import ExitCode, TriageError
from image_triage.core.settings import Settings, load_settings

app = typer.Typer(
    name="image-triage",
    help="Local, deterministic photo triage: analyze, group, rate and select the best photos.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """Local, deterministic photo triage command group."""


def get_settings(
    ctx: typer.Context,
    config: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Load settings once per CLI invocation and cache them on the context."""
    cache = ctx.obj if isinstance(ctx.obj, dict) else {}
    key = (str(config) if config else "", tuple(sorted((overrides or {}).keys())))
    if key not in cache:
        cache[key] = load_settings(config, overrides)
    ctx.obj = cache
    return cache[key]


def _register_commands() -> None:
    from image_triage.cli.commands import config as config_command
    from image_triage.cli.commands import doctor as doctor_command
    from image_triage.cli.commands import models as models_command
    from image_triage.cli.commands import schema as schema_command

    app.command("doctor")(doctor_command.doctor)
    app.command("schema")(schema_command.schema)
    app.add_typer(config_command.config_app, name="config")
    app.add_typer(models_command.models_app, name="models")

    for module_name, command_name in (
        ("scan", "scan"),
        ("analyze", "analyze"),
        ("score", "score"),
        ("select", "select"),
        ("plan", "plan"),
        ("apply", "apply"),
        ("export", "export"),
        ("report", "report"),
        ("run", "run"),
        ("benchmark", "benchmark"),
        ("gui", "gui"),
    ):
        try:
            module = __import__(f"image_triage.cli.commands.{module_name}", fromlist=[command_name])
        except ImportError:
            continue
        app.command(command_name)(getattr(module, command_name))


_register_commands()


def main() -> int:
    """Console entry point with stable exit codes."""
    try:
        app()
    except TriageError as exc:
        emit_error(exc.to_dict())
        return int(exc.exit_code)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:  # pragma: no cover - last-resort guard
        emit_error(
            {
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "exit_code": int(ExitCode.INTERNAL),
                    "details": {},
                }
            }
        )
        return int(ExitCode.INTERNAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
