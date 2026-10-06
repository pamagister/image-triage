"""Technical image quality metrics on a grayscale preview."""

import cv2
import numpy as np

TILES = 4


def sharpness(gray: np.ndarray) -> float:
    """Laplacian variance of the sharpest image regions.

    The image is split into a TILES x TILES grid and the 90th percentile of the
    per-tile variances is used, so a sharp subject in front of a blurred
    background still counts as sharp.
    """
    # Light denoise so high-ISO grain is not mistaken for detail.
    lap = cv2.Laplacian(cv2.GaussianBlur(gray, (3, 3), 0), cv2.CV_64F)
    h, w = lap.shape
    variances = [
        lap[y * h // TILES : (y + 1) * h // TILES, x * w // TILES : (x + 1) * w // TILES].var()
        for y in range(TILES)
        for x in range(TILES)
    ]
    return float(np.percentile(variances, 90))


def exposure(gray: np.ndarray) -> float:
    """Exposure quality in [0, 1]: penalizes clipped highlights/shadows and extreme brightness."""
    clipped_high = float(np.mean(gray >= 250))
    clipped_low = float(np.mean(gray <= 5))
    mean = float(gray.mean()) / 255.0
    # Mean brightness between 0.15 and 0.75 is fine (dark venues are normal).
    brightness_penalty = max(0.0, 0.15 - mean, mean - 0.75) * 2
    score = 1.0 - 3 * clipped_high - 1.5 * clipped_low - brightness_penalty
    return float(np.clip(score, 0.0, 1.0))
