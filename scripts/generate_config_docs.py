"""Generate config.yaml and the CLI/config documentation from the pydantic models."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import get_args, get_origin

import yaml
from typer.main import get_command

from image_triage.cli.app import app
from image_triage.core.settings import Settings

ROOT = Path(__file__).parents[1]
DEFAULT_CONFIG = ROOT / "config.yaml"
DEFAULT_CLI_DOC = ROOT / "docs/usage/cli.md"
DEFAULT_CONFIG_DOC = ROOT / "docs/usage/config.md"


def default_settings() -> Settings:
    """Defaults without reading the ambient YAML file or environment."""
    return Settings.model_validate({})


def generate_config() -> None:
    """Write the documented default YAML configuration."""
    payload = default_settings().model_dump(mode="json")
    header = (
        "# image-triage configuration\n"
        "# Precedence: CLI options > IMAGE_TRIAGE_* environment variables > this file > defaults.\n"
    )
    DEFAULT_CONFIG.write_text(
        header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Generated: {DEFAULT_CONFIG}")


def _type_name(annotation: object) -> str:
    origin = get_origin(annotation)
    if origin is not None:
        args = ", ".join(_type_name(arg) for arg in get_args(annotation))
        return f"{getattr(origin, '__name__', origin)}[{args}]"
    return getattr(annotation, "__name__", str(annotation))


def generate_config_doc() -> None:
    """Write docs/usage/config.md from the nested settings model."""
    settings = default_settings()
    lines = [
        "# Configuration",
        "",
        "Configuration precedence is **CLI options > `IMAGE_TRIAGE_*` environment variables > "
        "`image-triage.yaml` > defaults**. Nested environment variables use `__`, for example "
        "`IMAGE_TRIAGE_SCORING__SHARPNESS_WEIGHT=0.5`.",
        "",
        "Generate a starter file with `image-triage config init`, inspect the effective values "
        "with `image-triage config show`, and validate them with `image-triage config validate`.",
        "",
        "The generated `config.yaml` contains the same defaults.",
        "",
    ]
    for section_name, section_field in Settings.model_fields.items():
        section = getattr(settings, section_name)
        lines.append(f'## "{section_name}" {{#{section_name}}}')
        lines.append("")
        if section_field.description:
            lines.append(section_field.description)
            lines.append("")
        lines.append("| Name | Type | Default |")
        lines.append("|---|---|---|")
        for field_name, field in type(section).model_fields.items():
            value = getattr(section, field_name)
            if isinstance(value, Path):
                rendered = f"`{value}`"
            elif isinstance(value, list):
                rendered = f"`{json.dumps(value)}`"
            else:
                rendered = f"`{json.dumps(value, default=str)}`"
            lines.append(f"| {field_name} | {_type_name(field.annotation)} | {rendered} |")
        lines.append("")
    DEFAULT_CONFIG_DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated: {DEFAULT_CONFIG_DOC}")


def generate_cli_doc() -> None:
    """Write docs/usage/cli.md from the Typer command tree."""
    root = get_command(app)
    lines = [
        "# Command Line Interface",
        "",
        "All commands support `--config` to point at a YAML file. Human logs go to stderr; "
        "machine-readable output goes to stdout with `--json` where available. "
        "`analyze --ndjson` streams one JSON object per progress event.",
        "",
        "For development from a source checkout, use `python -m image_triage` instead of "
        "`image-triage`.",
        "",
        "## Commands",
        "",
    ]
    for name in root.commands:  # type: ignore[union-attr]
        lines.append(f"### `{name}`")
        lines.append("")
        result = subprocess.run(
            [sys.executable, "-m", "image_triage", name, "--help"],
            capture_output=True,
            text=True,
            env={**os.environ, "COLUMNS": "100", "NO_COLOR": "1"},
            check=False,
        )
        lines.append("```text")
        lines.append((result.stdout or result.stderr).strip())
        lines.append("```")
        lines.append("")
    DEFAULT_CLI_DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated: {DEFAULT_CLI_DOC}")


if __name__ == "__main__":
    generate_config()
    generate_config_doc()
    generate_cli_doc()
