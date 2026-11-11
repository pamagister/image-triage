"""``image-triage schema``: print published JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from image_triage.cli.output import emit_json
from image_triage.core.errors import UsageError

SCHEMA_DIR = Path(__file__).parents[2] / "report" / "schema"
SCHEMAS = {
    "report": "report.schema.json",
    "plan": "plan.schema.json",
    "ndjson": "ndjson.schema.json",
}


def schema(
    schema_name: str = typer.Argument("report", help="report, plan or ndjson."),
    output: Path | None = typer.Option(None, "--output", help="Write schema to a file."),
) -> None:
    """Print a versioned JSON Schema used by the CLI."""
    filename = SCHEMAS.get(schema_name)
    if filename is None:
        raise UsageError(f"unknown schema: {schema_name}", available=sorted(SCHEMAS))
    path = SCHEMA_DIR / filename
    if not path.is_file():
        raise UsageError(f"schema file missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"wrote {schema_name} schema to {output}")
    else:
        emit_json(document)
