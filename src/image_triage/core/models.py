"""Domain models and enumerations shared by the CLI, analysis and GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

SCORING_VERSION = "1.1.0"
SELECTION_VERSION = "1.0.0"
METRIC_VERSION = "1.1.0"
GROUP_VERSION = "1.0.0"
EVENT_VERSION = "1.0.0"


class BlurKind(StrEnum):
    """How an image lost sharpness."""

    NONE = "none"
    DEFOCUS = "defocus"
    MOTION = "motion"
    UNKNOWN = "unknown"


class ExportMode(StrEnum):
    """How selected originals are placed in the output folder."""

    COPY = "copy"
    HARDLINK = "hardlink"
    SYMLINK = "symlink"


class Provider(StrEnum):
    """ONNX Runtime execution providers supported by the benchmark."""

    CPU = "CPUExecutionProvider"
    CUDA = "CUDAExecutionProvider"
    ROCM = "ROCMExecutionProvider"
    OPENVINO = "OpenVINOExecutionProvider"
    DIRECTML = "DmlExecutionProvider"


class RunStatus(StrEnum):
    """Lifecycle of a stored pipeline run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(StrEnum):
    """Lifecycle of a background job started by the GUI."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OverrideSource(StrEnum):
    """Where a soft rating/keep-reject override came from."""

    CLI = "cli"
    GUI = "gui"


@dataclass(slots=True)
class Detection:
    """One object detection with a box in relative coordinates."""

    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in 0..1

    @property
    def area(self) -> float:
        """Fraction of the image covered by the box."""
        x1, y1, x2, y2 = self.box
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "confidence": round(float(self.confidence), 6),
            "box": [round(float(v), 6) for v in self.box],
            "area": round(float(self.area), 6),
        }


@dataclass(slots=True)
class Metrics:
    """Quality and content metrics for one photo."""

    sharpness: float = 0.0
    sharpness_raw: float = 0.0
    sharpness_subject: float = 0.0
    sharpness_subject_raw: float = 0.0
    bokeh: float = 0.0
    blur_kind: BlurKind = BlurKind.NONE
    blur_confidence: float = 0.0
    blur_score: float = 0.0
    composition: float = 0.0
    composition_components: dict[str, float] = field(default_factory=dict)
    aesthetic: float = 0.0
    aesthetic_source: str = "heuristic"
    subject_score: float = 0.0
    subject_rarity: float = 0.0
    exposure: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "sharpness": round(float(self.sharpness), 6),
            "sharpness_raw": round(float(self.sharpness_raw), 6),
            "sharpness_subject": round(float(self.sharpness_subject), 6),
            "sharpness_subject_raw": round(float(self.sharpness_subject_raw), 6),
            "bokeh": round(float(self.bokeh), 6),
            "blur_kind": self.blur_kind.value,
            "blur_confidence": round(float(self.blur_confidence), 6),
            "blur_score": round(float(self.blur_score), 6),
            "composition": round(float(self.composition), 6),
            "composition_components": {
                k: round(float(v), 6) for k, v in self.composition_components.items()
            },
            "aesthetic": round(float(self.aesthetic), 6),
            "aesthetic_source": self.aesthetic_source,
            "subject_score": round(float(self.subject_score), 6),
            "subject_rarity": round(float(self.subject_rarity), 6),
            "exposure": round(float(self.exposure), 6),
        }


@dataclass(slots=True)
class Photo:
    """A photo plus all analysis results stored for it."""

    id: int | None = None
    location_id: int | None = None
    root_id: int | None = None
    root_path: str = ""
    path: str = ""
    digest: str = ""
    phash: str = ""
    taken: datetime | None = None
    width: int = 0
    height: int = 0
    camera_make: str | None = None
    camera_model: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    event_id: int | None = None
    group_id: int | None = None
    metrics: Metrics = field(default_factory=Metrics)
    detections: list[Detection] = field(default_factory=list)
    embedding: list[float] | None = None
    score: float = 0.0
    rating: int = 0
    flags: list[str] = field(default_factory=list)
    model_signature: str | None = None
    analyzed_at: datetime | None = None
    available: bool = True
    selected: bool = False
    reason: str = ""
    quota_rule: str = ""

    @property
    def absolute_path(self) -> Path:
        """Location of the original file, when the root is known."""
        return Path(self.root_path) / self.path if self.root_path else Path(self.path)

    @property
    def name(self) -> str:
        """File name without directories."""
        return self.path.rsplit("/", 1)[-1]

    @property
    def folder(self) -> str:
        """Relative parent folder, or ``.`` for a file at the root."""
        return self.path.rsplit("/", 1)[0] if "/" in self.path else "."

    def to_dict(self, include_gps: bool = False) -> dict[str, object]:
        """Return a stable, JSON-serializable representation."""
        data: dict[str, object] = {
            "id": self.id,
            "location_id": self.location_id,
            "root": self.root_path,
            "path": self.path,
            "digest": self.digest,
            "phash": self.phash,
            "taken": self.taken.isoformat() if self.taken else None,
            "width": self.width,
            "height": self.height,
            "camera": {
                "make": self.camera_make,
                "model": self.camera_model,
            },
            "event_id": self.event_id,
            "group_id": self.group_id,
            "metrics": self.metrics.to_dict(),
            "detections": [d.to_dict() for d in self.detections],
            "score": round(float(self.score), 6),
            "rating": self.rating,
            "flags": list(self.flags),
            "model_signature": self.model_signature,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "selected": self.selected,
            "reason": self.reason,
            "quota_rule": self.quota_rule,
        }
        if include_gps and self.gps_lat is not None and self.gps_lon is not None:
            data["gps"] = {"lat": self.gps_lat, "lon": self.gps_lon}
        return data


@dataclass(slots=True)
class PhotoLocation:
    """One stored location of a content-addressed photo."""

    id: int
    photo_id: int
    root_id: int
    root_path: str
    relative_path: str
    mtime: float | None = None
    analyzed_at: datetime | None = None
    available: bool = True

    @property
    def absolute_path(self) -> Path:
        """Original file path for this location."""
        return Path(self.root_path) / self.relative_path


@dataclass(slots=True)
class Event:
    """A cluster of photos taken together in time and place."""

    id: int | None = None
    start: datetime | None = None
    end: datetime | None = None
    label: str = ""
    source: str = "time"
    photo_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "label": self.label,
            "source": self.source,
            "photo_count": self.photo_count,
        }


@dataclass(slots=True)
class Group:
    """A similarity group (duplicates or a series)."""

    id: int | None = None
    method: str = "similarity"
    version: str = GROUP_VERSION
    member_count: int = 0


@dataclass(slots=True)
class Selection:
    """One photo chosen by a selection run."""

    photo_id: int
    rank: int
    score: float
    reason: str = ""
    quota_rule: str = ""


@dataclass(slots=True)
class Run:
    """A persisted pipeline run."""

    id: str
    command: str
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    config_hash: str = ""
    model_hashes: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status.value,
            "config_hash": self.config_hash,
            "model_hashes": dict(self.model_hashes),
            "counts": dict(self.counts),
        }


@dataclass(slots=True)
class Override:
    """A soft rating/keep-reject signal from the CLI or GUI."""

    photo_id: int
    rating: int | None = None
    keep: bool | None = None
    source: OverrideSource = OverrideSource.CLI
    created_at: datetime | None = None
