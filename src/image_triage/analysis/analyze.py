"""Analysis orchestration: scan, decode, measure, infer and persist per photo."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from blake3 import blake3
from imagehash import phash as perceptual_hash

from image_triage.core.errors import InputError, PartialFailure
from image_triage.core.models import (
    METRIC_VERSION,
    SCORING_VERSION,
    BlurKind,
    Detection,
    Metrics,
    Photo,
    Run,
    RunStatus,
)
from image_triage.core.settings import Settings
from image_triage.db.repository import Repository
from image_triage.io.decode import decode_preview
from image_triage.io.scan import file_digest, find_images, scan_file
from image_triage.metrics.aesthetic import aesthetic_score
from image_triage.metrics.composition import composition_score
from image_triage.metrics.exposure import exposure_score
from image_triage.metrics.sharpness import analyze_sharpness
from image_triage.metrics.subjects import (
    label_counts,
    subject_rarity,
    subject_score,
)
from image_triage.models.providers import select_provider
from image_triage.models.yolo import ObjectDetector

ProgressCallback = Callable[[dict[str, Any]], None]
COMPOSITION_VERSION = "1.0.0"


@dataclass(slots=True)
class AnalyzeResult:
    """Summary of an analysis run."""

    run_id: str
    total: int = 0
    analyzed: int = 0
    reused: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provider: str = "CPUExecutionProvider"
    model_signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total": self.total,
            "analyzed": self.analyzed,
            "reused": self.reused,
            "errors": self.errors,
            "warnings": self.warnings,
            "provider": self.provider,
            "model_signature": self.model_signature,
            "metric_version": METRIC_VERSION,
        }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analysis_signature(settings: Settings) -> str:
    """Stable signature of everything that affects per-photo metrics."""
    payload: dict[str, Any] = {
        "metric_version": METRIC_VERSION,
        "composition_version": COMPOSITION_VERSION,
        "scoring_version": SCORING_VERSION,
        "phash_version": "1.0.0",
        "preview_size": settings.analysis.preview_size,
        "draft": settings.analysis.draft,
        "yolo_enabled": settings.models.enabled,
        "yolo_confidence": settings.analysis.yolo_confidence,
        "aesthetic_enabled": settings.analysis.aesthetic_enabled,
        "sharpness_percentile": settings.scoring.sharpness_percentile,
        "subject_classes": sorted(settings.scoring.subject_classes),
    }
    if settings.models.yolo_path.is_file():
        payload["yolo_sha256"] = _file_hash(settings.models.yolo_path)
    if settings.models.aesthetic_path.is_file():
        payload["aesthetic_sha256"] = _file_hash(settings.models.aesthetic_path)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return blake3(encoded).hexdigest()


def _build_detector(settings: Settings, result: AnalyzeResult) -> ObjectDetector | None:
    if not settings.models.enabled:
        result.provider = "none"
        return None
    if not settings.models.yolo_path.is_file():
        result.provider = "none"
        result.warnings.append(
            f"YOLO model not found at {settings.models.yolo_path}; continuing without detections"
        )
        return None
    provider = select_provider(settings.models.provider)
    try:
        result.provider = provider
        return ObjectDetector(
            settings.models.yolo_path, settings.analysis.yolo_confidence, provider
        )
    except Exception as exc:
        result.provider = "none"
        result.warnings.append(f"YOLO model could not be loaded: {exc}")
        return None


def _analyze_one(
    path: Path,
    relative: str,
    settings: Settings,
    detector: ObjectDetector | None,
    signature: str,
) -> Photo:
    scan = scan_file(path)
    preview = decode_preview(path, settings.analysis.preview_size, settings.analysis.draft)
    gray = np.asarray(preview.convert("L"))
    detections: list[Detection] = []
    embedding: list[float] | None = None
    if detector is not None:
        detected = detector.detect(preview)
        detections = detected.detections
        if settings.analysis.save_embeddings:
            embedding = detected.embedding.astype(np.float32).tolist()
    sharpness = analyze_sharpness(gray, [item.box for item in detections])
    composition, components = composition_score(gray, detections)
    aesthetic = aesthetic_score(
        preview,
        gray,
        min(1.0, sharpness.raw / 100.0),
        settings.models.aesthetic_path if settings.analysis.aesthetic_enabled else None,
    )
    metrics = Metrics(
        sharpness=0.0,
        sharpness_raw=sharpness.raw,
        sharpness_subject=0.0,
        sharpness_subject_raw=sharpness.subject_raw,
        bokeh=sharpness.bokeh,
        blur_kind=sharpness.blur_kind,
        blur_confidence=sharpness.blur_confidence,
        composition=composition,
        composition_components=components,
        aesthetic=aesthetic.score,
        aesthetic_source=aesthetic.source,
        subject_score=subject_score(detections, set(settings.scoring.subject_classes)),
        exposure=exposure_score(gray),
    )
    flags = []
    if sharpness.blur_kind is not BlurKind.NONE and sharpness.blur_confidence >= 0.5:
        flags.append("blurry")
    return Photo(
        path=relative,
        digest=file_digest(path),
        phash=str(perceptual_hash(preview)),
        taken=scan.taken,
        width=scan.width,
        height=scan.height,
        camera_make=scan.camera_make,
        camera_model=scan.camera_model,
        gps_lat=scan.gps_lat,
        gps_lon=scan.gps_lon,
        metrics=metrics,
        detections=detections,
        embedding=embedding,
        model_signature=signature,
        analyzed_at=datetime.now(UTC),
        flags=flags,
    )


def _scan_paths(settings: Settings) -> tuple[Path, list[Path]]:
    root = Path(settings.input.root).expanduser().resolve()
    if not root.is_dir():
        raise InputError(f"input folder not found: {root}", path=str(root))
    exclude = [root / ".image-triage"]
    for name in settings.input.exclude:
        exclude.append(root / name)
    paths = [
        path
        for path in find_images(root, tuple(exclude))
        if not any(part in settings.input.exclude for part in path.relative_to(root).parts)
    ]
    return root, paths


def _normalize_metrics(repository: Repository, settings: Settings) -> None:
    photos = repository.all_photos()
    raw_values = [photo.metrics.sharpness_raw or photo.metrics.sharpness for photo in photos]
    subject_values = [
        photo.metrics.sharpness_subject_raw or photo.metrics.sharpness_subject for photo in photos
    ]
    reference = (
        float(np.percentile(raw_values, settings.scoring.sharpness_percentile))
        if raw_values
        else 0.0
    )
    subject_reference = (
        float(np.percentile(subject_values, settings.scoring.sharpness_percentile))
        if subject_values
        else 0.0
    )
    counts = label_counts(photos)
    sharpness_updates: list[tuple[int, float, float]] = []
    subject_updates: list[tuple[int, float, float, float]] = []
    for photo in photos:
        if photo.id is None:
            continue
        raw = photo.metrics.sharpness_raw or photo.metrics.sharpness
        normalized = float(np.clip(raw / reference, 0.0, 1.0)) if reference > 0 else 0.0
        photo.metrics.sharpness = normalized
        raw_subject = photo.metrics.sharpness_subject_raw
        normalized_subject = (
            float(np.clip(raw_subject / subject_reference, 0.0, 1.0))
            if subject_reference > 0
            else normalized
        )
        photo.metrics.sharpness_subject = normalized_subject
        rarity = subject_rarity(photo.detections, counts)
        photo.metrics.subject_rarity = rarity
        sharpness_updates.append((photo.id, normalized, normalized_subject))
        subject_updates.append(
            (photo.id, photo.metrics.subject_score, rarity, photo.metrics.aesthetic_source)
        )
    repository.update_sharpness(sharpness_updates)
    repository.update_subject_metrics(subject_updates)


def _deterministic_run_id(command: str, settings: Settings, material: str) -> str:
    encoded = "\x1f".join(
        [command, settings.fingerprint(), analysis_signature(settings), material]
    ).encode("utf-8")
    return blake3(encoded).hexdigest()[:16]


def analyze_library(
    settings: Settings,
    repository: Repository,
    *,
    progress: ProgressCallback | None = None,
    strict: bool = False,
    run_id: str | None = None,
) -> AnalyzeResult:
    """Analyze all images below the configured input root.

    Existing photos whose digest, metric version and model signature match are reused.
    Per-file errors are collected; with ``strict`` they raise :class:`PartialFailure`.

    Args:
        settings: Effective configuration.
        repository: Open state database.
        progress: Optional callback receiving NDJSON-ready progress dictionaries.
        strict: Fail when any file could not be analyzed.
        run_id: Existing run id to attach the analysis to.

    Returns:
        An :class:`AnalyzeResult` summary.
    """
    root, paths = _scan_paths(settings)
    signature = analysis_signature(settings)
    if run_id is None:
        run_id = _deterministic_run_id(
            "analyze", settings, "\x1f".join(path.relative_to(root).as_posix() for path in paths)
        )
    result = AnalyzeResult(run_id=run_id, total=len(paths))
    run = Run(
        id=result.run_id,
        command="analyze",
        started_at=datetime.now(UTC),
        config_hash=settings.fingerprint(),
    )
    repository.save_run(run)
    result.model_signature = signature

    def emit(event: dict[str, Any]) -> None:
        if progress is not None:
            progress(event)

    emit({"event": "start", "total": len(paths), "input": str(root)})
    if not paths:
        run.status = RunStatus.COMPLETED
        repository.finish_run(run)
        emit({"event": "summary", **result.to_dict()})
        return result

    detector = _build_detector(settings, result)
    existing = {photo.path: photo for photo in repository.all_photos()}

    def process(path: Path) -> tuple[str, Photo | None, bool, str | None]:
        relative = path.relative_to(root).as_posix()
        try:
            scan_file(path)
            digest = file_digest(path)
            cached = existing.get(relative)
            if (
                cached is not None
                and cached.digest == digest
                and cached.model_signature == signature
            ):
                return relative, cached, True, None
            photo = _analyze_one(path, relative, settings, detector, signature)
            if photo.digest != digest:
                photo.digest = digest
            return relative, photo, False, None
        except Exception as exc:  # per-file isolation
            return relative, None, False, f"{type(exc).__name__}: {exc}"

    analyzed = reused = 0
    with ThreadPoolExecutor(max_workers=settings.app.max_workers) as pool:
        futures = [pool.submit(process, path) for path in paths]
        for done, future in enumerate(as_completed(futures), start=1):
            relative, photo, was_reused, error = future.result()
            if error:
                result.errors.append({"path": relative, "error": error})
                emit({"event": "error", "path": relative, "error": error})
            elif photo is not None:
                if was_reused:
                    reused += 1
                else:
                    repository.upsert_photo(photo, metric_version=METRIC_VERSION)
                    analyzed += 1
                emit(
                    {
                        "event": "photo",
                        "path": relative,
                        "done": done,
                        "total": len(paths),
                        "reused": was_reused,
                    }
                )
            emit({"event": "progress", "done": done, "total": len(paths), "path": relative})

    result.analyzed = analyzed
    result.reused = reused
    result.errors.sort(key=lambda item: item["path"])

    _normalize_metrics(repository, settings)

    run.status = RunStatus.FAILED if strict and result.errors else RunStatus.COMPLETED
    run.counts = {
        "total": len(paths),
        "analyzed": analyzed,
        "reused": reused,
        "errors": len(result.errors),
        "photos": repository.count_photos(),
    }
    repository.finish_run(run)
    emit({"event": "summary", **result.to_dict()})

    if strict and result.errors:
        raise PartialFailure(
            f"{len(result.errors)} file(s) could not be analyzed",
            errors=result.errors,
        )
    return result
