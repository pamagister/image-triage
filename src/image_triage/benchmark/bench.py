"""Provider detection and per-stage benchmark on a small sample."""

from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path
from typing import Any

import numpy as np

from image_triage.core.errors import InputError, ModelError
from image_triage.core.settings import Settings
from image_triage.io.decode import decode_preview
from image_triage.io.scan import file_digest, find_images, scan_file
from image_triage.metrics.aesthetic import aesthetic_score
from image_triage.metrics.composition import composition_score
from image_triage.metrics.sharpness import analyze_sharpness
from image_triage.models.providers import available_providers, select_provider
from image_triage.models.yolo import ObjectDetector


def _sample_paths(settings: Settings, limit: int) -> tuple[Path, list[Path]]:
    root = Path(settings.input.root).expanduser().resolve()
    if not root.is_dir() and Path("images").is_dir():
        root = Path("images").resolve()
    if not root.is_dir():
        raise InputError(f"benchmark input not found: {root}", path=str(root))
    exclude = tuple(root / name for name in settings.input.exclude) + (root / ".image-triage",)
    paths = [path for path in find_images(root, exclude) if path.is_file()]
    if not paths:
        raise InputError(f"no images found for benchmark: {root}", path=str(root))
    return root, paths[: max(1, limit)]


def run_benchmark(settings: Settings, limit: int = 20) -> dict[str, Any]:
    """Measure per-stage timing and peak memory on up to ``limit`` sample images."""
    root, paths = _sample_paths(settings, limit)
    providers = available_providers()
    provider = select_provider(settings.models.provider)
    detector: ObjectDetector | None = None
    if settings.models.enabled and settings.models.yolo_path.is_file():
        try:
            detector = ObjectDetector(
                settings.models.yolo_path, settings.analysis.yolo_confidence, provider
            )
        except Exception as exc:
            raise ModelError(f"could not load YOLO model: {exc}") from exc

    stages: dict[str, float] = {
        "scan": 0.0,
        "decode": 0.0,
        "sharpness": 0.0,
        "composition": 0.0,
        "yolo": 0.0,
        "aesthetic": 0.0,
    }
    tracemalloc.start()
    started = time.perf_counter()
    for path in paths:
        start = time.perf_counter()
        scan_file(path)
        file_digest(path)
        stages["scan"] += time.perf_counter() - start

        start = time.perf_counter()
        preview = decode_preview(path, settings.analysis.preview_size, settings.analysis.draft)
        stages["decode"] += time.perf_counter() - start

        gray = np.asarray(preview.convert("L"))
        start = time.perf_counter()
        analyze_sharpness(gray)
        stages["sharpness"] += time.perf_counter() - start

        detections = []
        if detector is not None:
            start = time.perf_counter()
            detections = detector.detect(preview).detections
            stages["yolo"] += time.perf_counter() - start

        start = time.perf_counter()
        composition_score(gray, detections)
        stages["composition"] += time.perf_counter() - start

        start = time.perf_counter()
        aesthetic_score(
            preview,
            gray,
            0.5,
            settings.models.aesthetic_path if settings.analysis.aesthetic_enabled else None,
        )
        stages["aesthetic"] += time.perf_counter() - start
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    count = len(paths)
    report: dict[str, Any] = {
        "input": str(root),
        "photos": count,
        "provider_available": providers,
        "provider": provider,
        "batch_size": settings.analysis.batch_size,
        "preview_size": settings.analysis.preview_size,
        "total_s": round(elapsed, 4),
        "per_photo_ms": round(elapsed / count * 1000, 2),
        "per_stage_ms": {name: round(value / count * 1000, 2) for name, value in stages.items()},
        "peak_memory_mb": round(peak / (1 << 20), 2),
    }
    target = root / ".image-triage" / "bench.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(target)
    return report
