"""Sharpness and blur-type analysis on a grayscale preview."""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from image_triage.core.models import BlurKind

TILES = 4

#: Below this absolute Laplacian variance a region counts as soft rather than merely relative.
SOFT_REGION = 25.0
#: Minimum crop size (pixels) for a usable subject measurement.
MIN_REGION = 8
#: Default half-size of the saliency window when no detection box is available.
SALIENCY_HALF = 0.2


@dataclass(slots=True)
class SharpnessResult:
    """Raw global sharpness, subject sharpness, bokeh and the classified blur type."""

    raw: float
    subject_raw: float
    bokeh: float
    blur_kind: BlurKind
    blur_confidence: float
    blur_score: float


def _laplacian(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.Laplacian(blurred, cv2.CV_64F)


def _tile_variances(gray: np.ndarray) -> list[float]:
    lap = _laplacian(gray)
    height, width = lap.shape
    return [
        float(
            lap[
                y * height // TILES : (y + 1) * height // TILES,
                x * width // TILES : (x + 1) * width // TILES,
            ].var()
        )
        for y in range(TILES)
        for x in range(TILES)
    ]


def raw_sharpness(gray: np.ndarray) -> float:
    """90th percentile of per-tile Laplacian variance.

    Splitting the image into tiles and taking a high percentile keeps a sharp subject
    sharp even when most of the frame (for example a blurred background) is soft.
    """
    variances = _tile_variances(gray)
    return float(np.percentile(variances, 90)) if variances else 0.0


def _box_crop(gray: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray | None:
    """Crop a relative box to pixels, or ``None`` when it is too small to measure."""
    height, width = gray.shape
    x1 = max(0, min(width - 1, int(box[0] * width)))
    y1 = max(0, min(height - 1, int(box[1] * height)))
    x2 = max(x1 + 1, min(width, int(np.ceil(box[2] * width))))
    y2 = max(y1 + 1, min(height, int(np.ceil(box[3] * height))))
    if x2 - x1 < MIN_REGION or y2 - y1 < MIN_REGION:
        return None
    return gray[y1:y2, x1:x2]


def saliency_box(gray: np.ndarray) -> tuple[float, float, float, float]:
    """A window around the strongest edges, used when no detection box exists."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    energy = cv2.magnitude(gx, gy)
    default = (0.5 - SALIENCY_HALF, 0.5 - SALIENCY_HALF, 0.5 + SALIENCY_HALF, 0.5 + SALIENCY_HALF)
    if float(energy.sum()) <= 1e-6:
        return default
    mask = energy >= float(np.percentile(energy, 90))
    if not mask.any():
        return default
    ys, xs = np.nonzero(mask)
    weights = energy[ys, xs]
    cx = float(np.average(xs, weights=weights)) / max(1, energy.shape[1] - 1)
    cy = float(np.average(ys, weights=weights)) / max(1, energy.shape[0] - 1)
    return (
        max(0.0, cx - SALIENCY_HALF),
        max(0.0, cy - SALIENCY_HALF),
        min(1.0, cx + SALIENCY_HALF),
        min(1.0, cy + SALIENCY_HALF),
    )


def largest_box(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    """The largest detection box, which is the most likely main subject."""
    return max(boxes, key=lambda item: (item[2] - item[0]) * (item[3] - item[1]))


def subject_sharpness(gray: np.ndarray, boxes: list[tuple[float, float, float, float]]) -> float:
    """Laplacian variance inside the main subject box.

    ``boxes`` are relative ``(x1, y1, x2, y2)`` detection boxes; the largest one wins. When
    no box is usable the saliency window is measured instead, so the caller always gets a
    value describing where the eye looks rather than the whole frame.
    """
    crop = _box_crop(gray, largest_box(boxes) if boxes else saliency_box(gray))
    if crop is None:
        return raw_sharpness(gray)
    return float(_laplacian(crop).var())


def _background_variances(gray: np.ndarray, box: tuple[float, float, float, float]) -> list[float]:
    """Tile variances whose centre lies outside the subject box."""
    variances = _tile_variances(gray)
    outside: list[float] = []
    for y in range(TILES):
        for x in range(TILES):
            cx = (x + 0.5) / TILES
            cy = (y + 0.5) / TILES
            if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
                continue
            outside.append(variances[y * TILES + x])
    return outside


def bokeh_score(
    gray: np.ndarray, box: tuple[float, float, float, float], subject_raw: float
) -> float:
    """Separated-subject signal in 0..1: strong when the subject is sharp and the rest is not.

    This is a deliberate aesthetic signal, not a defect. It stays at 0 when the subject is
    not actually sharp, so a uniformly soft frame cannot claim bokeh.
    """
    if subject_raw <= SOFT_REGION:
        return 0.0
    outside = _background_variances(gray, box)
    subject_factor = float(np.clip(subject_raw / (4.0 * SOFT_REGION), 0.0, 1.0))
    if not outside:
        return subject_factor
    background = float(np.median(outside))
    separation = (subject_raw - background) / subject_raw
    return float(np.clip(separation, 0.0, 1.0) * subject_factor)


def _gradient_anisotropy(gray: np.ndarray) -> float:
    """How directional the gradient energy is (0 = isotropic, 1 = purely directional)."""
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    energy_x = float(np.mean(gx * gx))
    energy_y = float(np.mean(gy * gy))
    total = energy_x + energy_y
    if total <= 1e-9:
        return 0.0
    return abs(energy_x - energy_y) / total


def absolute_blur_score(
    detail: float,
    *,
    sharp_reference: float = 120.0,
    blur_reference: float = 5.0,
    floor: float = 0.02,
) -> float:
    """Map absolute detail to a continuous 0..1 blur score.

    ``detail`` is a Laplacian variance. The mapping is logarithmic so both sharp and very
    soft images use the full range: ``sharp_reference`` maps to ``floor`` and
    ``blur_reference`` maps to 1.0. Every photo receives a value; there is no dead zone.
    """
    if detail <= 0.0 or detail <= blur_reference:
        return 1.0
    if detail >= sharp_reference:
        return floor
    span = math.log(sharp_reference) - math.log(blur_reference)
    if span <= 0.0:
        return floor
    fraction = (math.log(sharp_reference) - math.log(detail)) / span
    return float(min(1.0, max(floor, floor + (1.0 - floor) * fraction)))


def _classify(detail: float, anisotropy: float) -> tuple[BlurKind, float]:
    """Classify blur from the subject-region detail and gradient direction."""
    if detail >= SOFT_REGION:
        return BlurKind.NONE, 0.0
    blur_amount = float(np.clip((SOFT_REGION - detail) / SOFT_REGION, 0.0, 1.0))
    if anisotropy >= 0.30:
        confidence = float(np.clip((anisotropy - 0.20) / 0.35, 0.0, 1.0)) * blur_amount
        return BlurKind.MOTION, confidence
    confidence = float(np.clip(1.0 - anisotropy / 0.30, 0.0, 1.0)) * blur_amount
    if confidence <= 0.05:
        return BlurKind.UNKNOWN, 0.0
    return BlurKind.DEFOCUS, confidence


def analyze_sharpness(
    gray: np.ndarray,
    boxes: list[tuple[float, float, float, float]] | None = None,
    *,
    sharp_reference: float = 120.0,
    blur_reference: float = 5.0,
    floor: float = 0.02,
) -> SharpnessResult:
    """Compute global and subject sharpness, bokeh, and classify defocus versus motion blur.

    With detection boxes the blur decision uses the subject region, so a sharp subject in
    front of a deliberately blurred background is not reported as defocus blur. Without
    boxes the whole frame decides. The classification is conservative: low absolute detail
    is required before any blur type is reported.
    """
    boxes = boxes or []
    raw = raw_sharpness(gray)
    subject = subject_sharpness(gray, boxes)
    box = largest_box(boxes) if boxes else saliency_box(gray)
    bokeh = bokeh_score(gray, box, subject)
    detail = subject if boxes else raw
    blur_kind, confidence = _classify(detail, _gradient_anisotropy(gray))
    blur_score = absolute_blur_score(
        detail,
        sharp_reference=sharp_reference,
        blur_reference=blur_reference,
        floor=floor,
    )
    return SharpnessResult(
        raw=raw,
        subject_raw=subject,
        bokeh=bokeh,
        blur_kind=blur_kind,
        blur_confidence=confidence,
        blur_score=blur_score,
    )
