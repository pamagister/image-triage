"""``image-triage benchmark``: provider detection and per-stage timing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from image_triage.benchmark.bench import run_benchmark
from image_triage.cli.app import get_settings
from image_triage.cli.output import emit_json, print_table


def benchmark(
    ctx: typer.Context,
    input_dir: Path | None = typer.Option(None, "--input", help="Sample library root."),
    limit: int = typer.Option(20, "--limit", help="Number of sample photos."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Detect ONNX providers and measure analysis stages on sample photos."""
    overrides: dict[str, Any] = {}
    if input_dir is not None:
        overrides["input"] = {"root": input_dir}
    settings = get_settings(ctx, config, overrides)
    report = run_benchmark(settings, limit)
    if json_output:
        emit_json(report)
    else:
        print_table(
            [
                {"stage": stage, "ms_per_photo": value}
                for stage, value in report["per_stage_ms"].items()
            ],
            ["stage", "ms_per_photo"],
        )
        typer.echo(
            f"{report['photos']} photos, {report['per_photo_ms']} ms/photo, "
            f"provider {report['provider']}, peak {report['peak_memory_mb']} MB"
        )
        typer.echo(f"report: {report['output']}")
