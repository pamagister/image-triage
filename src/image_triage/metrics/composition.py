"""Composition metrics: subject placement, headroom, clipping, horizon and clutter."""

from __future__ import annotations

import math

import cv2
import numpy as np

from image_triage.core.models import Detection

THIRDS = ((1 / 3, 1 / 3), (2 / 3, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 2 / 3))
COMPONENT_WEIGHTS = {
    "placement": 0.30,
    "subject_size": 0.15,
    "headroom": 0.10,
    "clipping": 0.20,
    "horizon": 0.15,
    "clutter": 0.10,
}


def _clamp(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _saliency_centroid(gray: np.ndarray) -> tuple[float, float]:
    """Centroid of the strongest edges, a saliency proxy for images without detections."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    energy = cv2.magnitude(gx, gy)
    total = float(energy.sum())
    if total <= 1e-6:
        return 0.5, 0.5
    threshold = float(np.percentile(energy, 90))
    mask = energy >= threshold
    if not mask.any():
        return 0.5, 0.5
    ys, xs = np.nonzero(mask)
    weights = energy[ys, xs]
    return float(np.average(xs, weights=weights)) / (energy.shape[1] - 1), float(
        np.average(ys, weights=weights)
    ) / (energy.shape[0] - 1)


def _placement_score(point: tuple[float, float]) -> float:
    distance = min(math.hypot(point[0] - x, point[1] - y) for x, y in THIRDS)
    return _clamp(1.0 - distance / 0.35)


def _headroom_score(box: tuple[float, float, float, float]) -> float:
    top = box[1]
    if 0.03 <= top <= 0.25:
        return 1.0
    if top < 0.03:
        return _clamp(0.5 + top / 0.03 * 0.5)
    return _clamp(1.0 - (top - 0.25) / 0.50)


def _clipping_score(box: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = box
    outside = max(0.0, -x1) + max(0.0, -y1) + max(0.0, x2 - 1.0) + max(0.0, y2 - 1.0)
    width = max(1e-6, min(1.0, x2) - max(0.0, x1))
    height = max(1e-6, min(1.0, y2) - max(0.0, y1))
    return _clamp(1.0 - outside / (width + height))


def _subject_size_score(area: float) -> float:
    if 0.05 <= area <= 0.60:
        return 1.0
    if area < 0.05:
        return _clamp(area / 0.05)
    return _clamp(1.0 - (area - 0.60) / 0.40)


def _horizon_score(gray: np.ndarray) -> float | None:
    """Level score from long near-horizontal Hough lines, or None when absent."""
    edges = cv2.Canny(gray, 50, 150)
    height, width = edges.shape
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=60, minLineLength=int(width * 0.25), maxLineGap=20
    )
    if lines is None:
        return None
    best: float | None = None
    for line in lines:
        x1, y1, x2, y2 = (int(value) for value in np.asarray(line).reshape(-1)[:4])
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if angle > 90:
            angle -= 180
        if angle < -90:
            angle += 180
        if abs(angle) > 20:
            continue
        score = _clamp(1.0 - abs(angle) / 8.0)
        length = math.hypot(x2 - x1, y2 - y1)
        weighted = score * min(1.0, length / (width * 0.5))
        if best is None or weighted > best:
            best = weighted
    return best


def _clutter_score(gray: np.ndarray) -> float:
    edges = cv2.Canny(gray, 50, 150)
    density = float(np.count_nonzero(edges)) / max(1, edges.size)
    return _clamp(1.0 - density * 3.0)


def composition_score(
    gray: np.ndarray, detections: list[Detection] | None = None
) -> tuple[float, dict[str, float]]:
    """Return a 0..1 composition score and its component breakdown.

    Components are combined with fixed weights, renormalised when the horizon or a
    subject is absent. The result is deterministic for identical pixels and detections.
    """
    detections = detections or []
    components: dict[str, float] = {}

    subject = max(detections, key=lambda d: d.confidence, default=None)
    if subject is not None:
        box = subject.box
        point = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        components["placement"] = _placement_score(point)
        components["headroom"] = _headroom_score(box)
        components["clipping"] = _clipping_score(box)
        components["subject_size"] = _subject_size_score(subject.area)
    else:
        components["placement"] = _placement_score(_saliency_centroid(gray))
        components["headroom"] = 0.6
        components["clipping"] = 1.0
        components["subject_size"] = 0.6

    horizon = _horizon_score(gray)
    if horizon is not None:
        components["horizon"] = horizon
    components["clutter"] = _clutter_score(gray)

    weight_sum = sum(COMPONENT_WEIGHTS[name] for name in components)
    total = sum(COMPONENT_WEIGHTS[name] * value for name, value in components.items())
    return _clamp(total / weight_sum), components
