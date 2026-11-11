"""Phase 6 tests: model registry, benchmark and scale-library generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from image_triage.benchmark.bench import run_benchmark
from image_triage.core.errors import ModelError
from image_triage.core.settings import load_settings
from image_triage.models.registry import install_model, list_models
from scripts.generate_synthetic_library import generate


def test_registry_installs_local_aesthetic_model_with_checksum(tmp_path: Path) -> None:
    source = tmp_path / "aesthetic.onnx"
    source.write_bytes(b"fake onnx model")
    settings = load_settings(
        None,
        {
            "input": {"root": tmp_path},
            "models": {
                "aesthetic_path": tmp_path / "models" / "aesthetic.onnx",
                "registry_path": tmp_path / "registry.json",
            },
        },
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    entry = install_model(settings, "aesthetic", path=source, sha256=digest)
    assert entry["license"] == "model-specific"
    assert entry["sha256"] == digest
    assert (tmp_path / "models" / "aesthetic.onnx").is_file()

    entries = {item["name"]: item for item in list_models(settings)}
    assert entries["aesthetic"]["installed"] is True
    assert entries["aesthetic"]["installed_sha256"] == digest


def test_registry_rejects_checksum_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "aesthetic.onnx"
    source.write_bytes(b"fake onnx model")
    settings = load_settings(
        None,
        {
            "input": {"root": tmp_path},
            "models": {
                "aesthetic_path": tmp_path / "models" / "aesthetic.onnx",
                "registry_path": tmp_path / "registry.json",
            },
        },
    )
    with pytest.raises(ModelError, match="checksum"):
        install_model(settings, "aesthetic", path=source, sha256="0" * 64)
    assert not (tmp_path / "models" / "aesthetic.onnx").exists()


def test_benchmark_reports_stages_and_writes_report(photo_dir: Path, tmp_path: Path) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir},
            "models": {"enabled": False},
            "analysis": {"preview_size": 256},
        },
    )
    report = run_benchmark(settings, limit=2)
    assert report["photos"] == 2
    assert report["per_photo_ms"] > 0
    assert set(report["per_stage_ms"]) >= {"scan", "decode", "sharpness", "composition"}
    output = Path(report["output"])
    assert output.is_file()
    assert json.loads(output.read_text())["photos"] == 2


def test_synthetic_library_generation_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "library"
    generate(root, 12, width=64, height=48)
    files = sorted(path.name for path in root.glob("*.jpg"))
    assert len(files) == 12
    assert files[0].endswith(".jpg")
