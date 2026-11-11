"""Subject presence and corpus-level label rarity."""

from __future__ import annotations

import math
from collections import Counter

from image_triage.core.models import Detection, Photo

SUBJECT_FULL_AREA = 0.05
DEFAULT_SUBJECT_CLASSES = frozenset(
    {
        "person",
        "bird",
        "cat",
        "dog",
        "horse",
        "sheep",
        "cow",
        "elephant",
        "bear",
        "zebra",
        "giraffe",
        "car",
        "bicycle",
        "motorcycle",
        "airplane",
        "boat",
    }
)


def subject_score(detections: list[Detection], classes: set[str] | frozenset[str]) -> float:
    """Prominence of the best subject: confidence x min(1, area / 5%)."""
    return max(
        (
            d.confidence * min(1.0, d.area / SUBJECT_FULL_AREA)
            for d in detections
            if d.label in classes
        ),
        default=0.0,
    )


def label_counts(photos: list[Photo]) -> Counter[str]:
    """Count detected labels across the current corpus."""
    counts: Counter[str] = Counter()
    for photo in photos:
        counts.update({d.label for d in photo.detections})
    return counts


def rarity_score(count: int) -> float:
    """Rarity in 0..1: 1 / (1 + log(1 + count))."""
    return 1.0 / (1.0 + math.log(1.0 + max(0, count)))


def subject_rarity(detections: list[Detection], counts: Counter[str]) -> float:
    """Highest rarity among detected labels (0 when no subject was detected)."""
    if not detections:
        return 0.0
    return max(rarity_score(counts.get(d.label, 0)) for d in detections)


def subject_value(score: float, rarity: float) -> float:
    """Combine presence and rarity into the signal used by the scoring formula."""
    return float(max(0.0, min(1.0, score))) * (0.5 + 0.5 * float(max(0.0, min(1.0, rarity))))
