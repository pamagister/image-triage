"""``image-triage doctor``: verify the local environment."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import typer

from image_triage.cli.output import emit_json, print_table
from image_triage.core.settings import Settings
from image_triage.db.repository import Repository
from image_triage.db.schema import SCHEMA_VERSION


def _check(name: str, ok: bool, detail: object) -> dict[str, object]:
    return {"name": name, "ok": ok, "detail": detail}


def build_report(settings: Settings) -> dict[str, object]:
    """Run all environment checks and return a stable report."""
    checks: list[dict[str, object]] = []
    python_ok = sys.version_info >= (3, 12)
    checks.append(
        _check(
            "python",
            python_ok,
            {"version": platform.python_version(), "required": ">=3.12"},
        )
    )

    input_ok = settings.input.root.is_dir()
    checks.append(_check("input", input_ok, {"path": str(settings.input.root), "is_dir": input_ok}))

    db_path = settings.database_path
    db_ok = False
    db_detail: object = {"path": str(db_path)}
    try:
        repository = Repository.open(db_path)
        try:
            db_detail = {
                "path": str(db_path),
                "schema_version": SCHEMA_VERSION,
                "photos": repository.count_photos(),
            }
            db_ok = True
        finally:
            repository.close()
    except Exception as exc:  # pragma: no cover - diagnostic path
        db_detail = {"path": str(db_path), "error": str(exc)}
    checks.append(_check("database", db_ok, db_detail))

    for name, path in (
        ("yolo", settings.models.yolo_path),
        ("aesthetic", settings.models.aesthetic_path),
    ):
        exists = Path(path).is_file()
        checks.append(
            _check(
                f"model:{name}",
                exists or not settings.models.enabled,
                {"path": str(path), "installed": exists, "required": settings.models.enabled},
            )
        )

    providers = ["CPUExecutionProvider"]
    provider_detail: object = providers
    try:
        import onnxruntime as ort

        available = list(ort.get_available_providers())
        providers = available
        provider_detail = available
    except Exception as exc:  # pragma: no cover - diagnostic path
        provider_detail = {"error": str(exc)}
    checks.append(_check("onnxruntime", bool(providers), provider_detail))

    samples = [
        path
        for path in (Path("images").rglob("*") if Path("images").is_dir() else [])
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    checks.append(_check("samples", bool(samples), {"count": len(samples), "root": "images"}))

    return {
        "ok": all(bool(check["ok"]) for check in checks),
        "schema_version": SCHEMA_VERSION,
        "config": {
            "database": str(db_path),
            "input": str(settings.input.root),
            "models_enabled": settings.models.enabled,
        },
        "checks": checks,
    }


def doctor(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    config: Path | None = typer.Option(None, "--config", help="YAML config file."),
) -> None:
    """Check Python, database, models, ONNX providers and sample images."""
    from image_triage.cli.app import get_settings

    settings = get_settings(ctx, config)
    report = build_report(settings)
    if json_output:
        emit_json(report)
    else:
        print_table(
            [
                {"check": c["name"], "ok": "ok" if c["ok"] else "FAIL", "detail": str(c["detail"])}
                for c in report["checks"]
            ],
            ["check", "ok", "detail"],
        )
    if not report["ok"]:
        raise typer.Exit(1)
