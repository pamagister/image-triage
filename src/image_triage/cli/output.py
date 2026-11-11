"""Text, JSON and NDJSON renderers for human and agent output."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from typing import Any

import typer


def _dumps(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False, default=str)


def emit_json(data: Any) -> None:
    """Write one stable JSON document to stdout."""
    typer.echo(_dumps(data))


def emit_ndjson(events: Iterable[Any]) -> None:
    """Write one compact JSON object per line to stdout."""
    for event in events:
        typer.echo(json.dumps(event, sort_keys=False, ensure_ascii=False, default=str))


def emit_error(error: Any) -> None:
    """Write an error JSON document to stderr."""
    typer.echo(_dumps(error), err=True)


def print_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Minimal aligned table for human-readable output."""
    if not rows:
        typer.echo("No rows")
        return
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    typer.echo("  ".join(column.ljust(widths[column]) for column in columns))
    typer.echo("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        typer.echo("  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))


def stdout_is_tty() -> bool:
    """Whether stdout is attached to a terminal (used to suppress progress)."""
    return sys.stdout.isatty()
