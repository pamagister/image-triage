"""Analysis orchestration: scan, decode, measure, infer and persist per photo."""

from __future__ import annotations

import hashlib
import json
import threading
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
    missing: list[str] = field(default_factory=list)
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
            "missing": self.missing,
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
        "blur_sharp_reference": settings.blur.sharp_reference,
        "blur_blur_reference": settings.blur.blur_reference,
        "blur_floor": settings.blur.floor,
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
    root_path: str,
    digest: str | None = None,
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
    sharpness = analyze_sharpness(
        gray,
        [item.box for item in detections],
        sharp_reference=settings.blur.sharp_reference,
        blur_reference=settings.blur.blur_reference,
        floor=settings.blur.floor,
    )
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
        blur_score=sharpness.blur_score,
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
        root_path=root_path,
        digest=digest or file_digest(path),
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


def scan_plan(settings: Settings) -> list[tuple[Path, list[Path]]]:
    """Return de-overlapped ``(root, paths)`` pairs for every enabled watched root.

    A root contained by an earlier (shorter) root is skipped so nested libraries are not
    scanned twice.
    """
    roots = settings.watched_roots
    kept: list[Path] = []
    for root in sorted(roots, key=lambda path: (len(path.parts), str(path))):
        if any(root == other or root.is_relative_to(other) for other in kept):
            continue
        kept.append(root)

    plan: list[tuple[Path, list[Path]]] = []
    missing: list[Path] = []
    for root in kept:
        if not root.is_dir():
            missing.append(root)
            continue
        exclude = [root / ".image-triage"]
        exclude.extend(root / name for name in settings.input.exclude)
        paths = [
            path
            for path in find_images(root, tuple(exclude))
            if not any(part in settings.input.exclude for part in path.relative_to(root).parts)
        ]
        plan.append((root, paths))
    if not plan and missing:
        raise InputError(f"input folder not found: {missing[0]}", path=str(missing[0]))
    return plan


def _normalize_metrics(repository: Repository, settings: Settings) -> None:
    photos = repository.all_content()
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
    plan = scan_plan(settings)
    repository.sync_roots([root for root, _ in plan])
    signature = analysis_signature(settings)
    prepared: list[tuple[Path, str, Path, str]] = []
    pre_errors: list[dict[str, str]] = []

    def prepare(root: Path, path: Path) -> tuple[Path, str, Path, str] | None:
        relative = path.relative_to(root).as_posix()
        try:
            scan_file(path)
            return root, relative, path, file_digest(path)
        except Exception as exc:  # per-file isolation
            pre_errors.append({"path": relative, "error": f"{type(exc).__name__}: {exc}"})
            return None

    with ThreadPoolExecutor(max_workers=settings.app.max_workers) as pool:
        futures = [pool.submit(prepare, root, path) for root, paths in plan for path in paths]
        for future in as_completed(futures):
            item = future.result()
            if item is not None:
                prepared.append(item)
    prepared.sort(key=lambda item: (str(item[0]), item[1]))
    result = AnalyzeResult(run_id="", total=len(prepared))
    result.errors.extend(pre_errors)
    material = "\x1f".join(f"{root}/{relative}" for root, relative, _path, _digest in prepared)
    run_id = _deterministic_run_id("analyze", settings, material)
    result.run_id = run_id
    run = Run(
        id=run_id,
        command="analyze",
        started_at=datetime.now(UTC),
        config_hash=settings.fingerprint(),
    )
    repository.save_run(run)
    result.model_signature = signature

    def emit(event: dict[str, Any]) -> None:
        if progress is not None:
            progress(event)

    emit(
        {
            "event": "start",
            "total": len(prepared),
            "inputs": [str(root) for root, _ in plan],
        }
    )
    if not prepared:
        result.missing = repository.mark_missing_locations(set())
        run.status = RunStatus.COMPLETED
        repository.finish_run(run)
        emit({"event": "summary", **result.to_dict()})
        return result

    detector = _build_detector(settings, result)
    existing = {photo.digest: photo for photo in repository.all_content() if photo.digest}
    groups: dict[str, list[tuple[Path, str, Path, str]]] = {}
    for item in prepared:
        groups.setdefault(item[3], []).append(item)
    keep = {(str(root), relative) for root, relative, _path, _digest in prepared}
    lock = threading.Lock()

    def process_group(
        digest: str, entries: list[tuple[Path, str, Path, str]]
    ) -> tuple[Photo | None, bool, str | None]:
        cached = existing.get(digest)
        if cached is not None and cached.model_signature == signature:
            return cached, True, None
        root, relative, path, _digest = entries[0]
        try:
            photo = _analyze_one(path, relative, settings, detector, signature, str(root), digest)
            with lock:
                existing[digest] = photo
            return photo, False, None
        except Exception as exc:  # per-file isolation
            return None, False, f"{type(exc).__name__}: {exc}"

    analyzed = reused = 0
    done = 0
    with ThreadPoolExecutor(max_workers=settings.app.max_workers) as pool:
        futures = {
            pool.submit(process_group, digest, entries): digest
            for digest, entries in groups.items()
        }
        for future in as_completed(futures):
            digest = futures[future]
            entries = groups[digest]
            photo, was_reused, error = future.result()
            if error:
                for _root, relative, _path, _digest in entries:
                    result.errors.append({"path": relative, "error": error})
                    emit({"event": "error", "path": relative, "error": error})
                done += len(entries)
                continue
            if photo is None:
                continue
            if was_reused:
                reused += len(entries)
            else:
                repository.upsert_photo(photo, metric_version=METRIC_VERSION)
                analyzed += 1
                reused += len(entries) - 1
            for root, relative, path, item_digest in entries:
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = None
                repository.upsert_scanned_location(
                    photo.id,
                    str(root),
                    relative,
                    digest=item_digest,
                    keep=keep,
                    mtime=mtime,
                    analyzed_at=photo.analyzed_at.isoformat() if photo.analyzed_at else None,
                )
                done += 1
                emit(
                    {
                        "event": "photo",
                        "path": relative,
                        "root": str(root),
                        "done": done,
                        "total": len(prepared),
                        "reused": was_reused,
                    }
                )
                emit(
                    {
                        "event": "progress",
                        "done": done,
                        "total": len(prepared),
                        "path": relative,
                    }
                )

    result.analyzed = analyzed
    result.reused = reused
    result.missing = repository.mark_missing_locations(keep)
    result.errors.sort(key=lambda item: item["path"])

    _normalize_metrics(repository, settings)

    run.status = RunStatus.FAILED if strict and result.errors else RunStatus.COMPLETED
    run.counts = {
        "total": len(prepared),
        "analyzed": analyzed,
        "reused": reused,
        "errors": len(result.errors),
        "missing": len(result.missing),
        "photos": repository.count_content(),
    }
    repository.finish_run(run)
    emit({"event": "summary", **result.to_dict()})

    if strict and result.errors:
        raise PartialFailure(
            f"{len(result.errors)} file(s) could not be analyzed",
            errors=result.errors,
        )
    return result
