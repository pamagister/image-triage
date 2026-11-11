"""Exposure quality signal (non-scoring in v1, kept for inspection)."""

from __future__ import annotations

import numpy as np


def exposure_score(gray: np.ndarray) -> float:
    """Penalise clipped highlights/shadows and extreme brightness, in 0..1."""
    clipped_high = float(np.mean(gray >= 250))
    clipped_low = float(np.mean(gray <= 5))
    mean = float(gray.mean()) / 255.0
    brightness_penalty = max(0.0, 0.15 - mean, mean - 0.75) * 2
    score = 1.0 - 3 * clipped_high - 1.5 * clipped_low - brightness_penalty
    return float(np.clip(score, 0.0, 1.0))
