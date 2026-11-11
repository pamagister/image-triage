"""Phase 2 tests: scan/decode, blur classification, composition and analysis."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from PIL import Image
from typer.testing import CliRunner

from image_triage.analysis.analyze import analyze_library
from image_triage.cli.app import app
from image_triage.core.errors import PartialFailure
from image_triage.core.models import BlurKind
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.io.scan import _gps_decimal, file_digest, scan_file
from image_triage.metrics.composition import composition_score
from image_triage.metrics.sharpness import analyze_sharpness
from image_triage.models.yolo import ObjectDetector
from tests.conftest import _scene, save_jpeg


def _gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def test_blur_classification_distinguishes_motion_and_defocus() -> None:
    scene = _scene(1)
    kernel = np.zeros((1, 21), dtype=np.float32)
    kernel[0, :] = 1 / 21
    motion = cv2.filter2D(scene, -1, kernel)
    defocus = cv2.GaussianBlur(scene, (0, 0), 6)

    assert analyze_sharpness(_gray(scene)).blur_kind is BlurKind.NONE
    assert analyze_sharpness(_gray(motion)).blur_kind is BlurKind.MOTION
    assert analyze_sharpness(_gray(motion)).blur_confidence > 0.0
    assert analyze_sharpness(_gray(defocus)).blur_kind is BlurKind.DEFOCUS


def test_composition_is_normalized_and_has_breakdown() -> None:
    scene = _scene(2)
    score, components = composition_score(_gray(scene))
    assert 0.0 <= score <= 1.0
    assert set(components) >= {"placement", "clipping", "clutter"}
    assert all(0.0 <= value <= 1.0 for value in components.values())


def test_scan_reads_exif_time_dimensions_and_digest(tmp_path: Path) -> None:
    path = save_jpeg(tmp_path / "photo.jpg", _scene(3), datetime(2020, 7, 4, 8, 30, 15))
    info = scan_file(path)
    assert info.taken == datetime(2020, 7, 4, 8, 30, 15)
    assert (info.width, info.height) == (900, 600)
    assert file_digest(path) == file_digest(path)


def test_gps_decimal_conversion() -> None:
    lat, lon = _gps_decimal(
        {
            1: "N",
            2: (50, 1, 2.4),
            3: "E",
            4: (8, 1, 3.6),
        }
    )
    assert lat == pytest.approx(50 + 1 / 60 + 2.4 / 3600)
    assert lon == pytest.approx(8 + 1 / 60 + 3.6 / 3600)
    south, west = _gps_decimal({1: "S", 2: (1, 1, 0), 3: "W", 4: (2, 1, 0)})
    assert south == pytest.approx(-1 - 1 / 60)
    assert west == pytest.approx(-2 - 1 / 60)


def test_corrupt_file_is_collected_or_fails_strict(photo_dir: Path, tmp_path: Path) -> None:
    (photo_dir / "broken.jpg").write_bytes(b"not an image")
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "state.db"},
            "models": {"enabled": False},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        result = analyze_library(settings, repository)
        assert result.analyzed == 4
        assert len(result.errors) == 1
        assert result.errors[0]["path"] == "broken.jpg"
    finally:
        repository.close()

    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "strict.db"},
            "models": {"enabled": False},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        with pytest.raises(PartialFailure):
            analyze_library(settings, repository, strict=True)
    finally:
        repository.close()


def test_analysis_is_resumable_and_stores_metrics(photo_dir: Path, tmp_path: Path) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "state.db"},
            "models": {"enabled": False},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        first = analyze_library(settings, repository)
        assert first.analyzed == 4 and first.reused == 0
        second = analyze_library(settings, repository)
        assert second.analyzed == 0 and second.reused == 4

        photos = repository.all_photos()
        assert len(photos) == 4
        assert all(0.0 <= photo.metrics.sharpness <= 1.0 for photo in photos)
        assert all(0.0 <= photo.metrics.composition <= 1.0 for photo in photos)
        assert any(photo.metrics.sharpness == 1.0 for photo in photos)
        assert all(photo.embedding is None for photo in photos)
        assert all(photo.metrics.aesthetic_source == "heuristic" for photo in photos)
    finally:
        repository.close()


def test_analyze_cli_emits_json_summary(photo_dir: Path, tmp_path: Path) -> None:
    config = tmp_path / "image-triage.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "input": {"root": str(photo_dir)},
                "models": {"enabled": False},
            }
        )
    )
    result = CliRunner().invoke(app, ["analyze", "--json", "--config", str(config)])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["analyzed"] == 4
    assert summary["errors"] == []
    assert summary["provider"] == "none"


def test_detector_returns_normalized_embedding() -> None:
    model = Path("res/yolo/yolo26n.onnx")
    if not model.is_file():
        pytest.skip("YOLO model not installed")
    detector = ObjectDetector(model, 0.5, "CPUExecutionProvider")
    result = detector.detect(Image.new("RGB", (900, 600), (120, 120, 120)))
    assert result.embedding.shape == (256,)
    assert np.linalg.norm(result.embedding) == pytest.approx(1.0, abs=1e-5)
    assert all(0.0 <= value <= 1.0 for det in result.detections for value in det.box)
