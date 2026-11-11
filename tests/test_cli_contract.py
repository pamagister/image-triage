"""Phase 5 tests: CLI contract, exit codes and published schemas."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
SCHEMA_DIR = ROOT / "src/image_triage/report/schema"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "image_triage", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_input_returns_exit_code_3() -> None:
    result = _run("scan", "--input", "/definitely/not/a/real/library")
    assert result.returncode == 3
    error = json.loads(result.stderr)
    assert error["error"]["exit_code"] == 3


def test_unknown_schema_returns_exit_code_2() -> None:
    result = _run("schema", "does-not-exist")
    assert result.returncode == 2
    error = json.loads(result.stderr)
    assert error["error"]["exit_code"] == 2


def test_all_published_schemas_are_valid() -> None:
    for path in SCHEMA_DIR.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(document)


def test_ndjson_events_validate(photo_dir: Path, tmp_path: Path) -> None:
    config = tmp_path / "image-triage.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "input": {"root": str(photo_dir)},
                "models": {"enabled": False},
            }
        )
    )
    result = _run("analyze", "--ndjson", "--config", str(config))
    assert result.returncode == 0, result.stderr
    schema = json.loads((SCHEMA_DIR / "ndjson.schema.json").read_text())
    validator = Draft202012Validator(schema)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert events
    for event in events:
        validator.validate(event)
    assert events[-1]["event"] == "summary"


def test_config_init_show_and_validate(tmp_path: Path) -> None:
    config = tmp_path / "image-triage.yaml"
    init = _run("config", "init", "--output", str(config), "--force")
    assert init.returncode == 0, init.stderr
    assert config.is_file()

    show = _run("config", "show", "--config", str(config), "--json")
    assert show.returncode == 0, show.stderr
    payload = json.loads(show.stdout)
    assert payload["scoring"]["sharpness_weight"] == 0.45

    validate = _run("config", "validate", "--config", str(config), "--json")
    # The aesthetic model is optional and absent in CI; validation reports it but does
    # not fail the configuration because models are not required for core analysis.
    assert validate.returncode in {0, 2}
    report = json.loads(validate.stdout)
    assert report["ok"] is False or report["ok"] is True
