"""``image-triage gui``: start the local web GUI."""

from __future__ import annotations

from pathlib import Path

import typer

from image_triage.cli.app import get_settings


def gui(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", help="Bind address."),
    port: int | None = typer.Option(None, "--port", help="Bind port."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Start the local FastAPI/htmx web interface."""
    overrides = {}
    if host is not None or port is not None:
        overrides["gui"] = {}
        if host is not None:
            overrides["gui"]["host"] = host
        if port is not None:
            overrides["gui"]["port"] = port
    settings = get_settings(ctx, config, overrides or None)

    try:
        import uvicorn

        from image_triage.gui.app import create_app
    except ImportError as exc:  # pragma: no cover - optional extra
        typer.echo(
            f"the gui extra is not installed: {exc}. Install with: uv sync --extra gui",
            err=True,
        )
        raise typer.Exit(4) from exc

    if settings.gui.host not in {"127.0.0.1", "localhost", "::1"}:
        typer.echo(
            "warning: binding beyond localhost exposes an unauthenticated local tool",
            err=True,
        )
    uvicorn.run(
        create_app(settings),
        host=settings.gui.host,
        port=settings.gui.port,
        log_level=settings.app.log_level.lower(),
    )
