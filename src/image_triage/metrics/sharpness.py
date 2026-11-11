"""Sharpness and blur-type analysis on a grayscale preview."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from image_triage.core.models import BlurKind

TILES = 4


@dataclass(slots=True)
class SharpnessResult:
    """Raw tile-based sharpness plus the classified blur type."""

    raw: float
    blur_kind: BlurKind
    blur_confidence: float


def raw_sharpness(gray: np.ndarray) -> float:
    """90th percentile of per-tile Laplacian variance.

    Splitting the image into tiles and taking a high percentile keeps a sharp subject
    sharp even when most of the frame (for example a blurred background) is soft.
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    lap = cv2.Laplacian(blurred, cv2.CV_64F)
    height, width = lap.shape
    variances = [
        lap[
            y * height // TILES : (y + 1) * height // TILES,
            x * width // TILES : (x + 1) * width // TILES,
        ].var()
        for y in range(TILES)
        for x in range(TILES)
    ]
    return float(np.percentile(variances, 90)) if variances else 0.0


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


def analyze_sharpness(gray: np.ndarray) -> SharpnessResult:
    """Compute raw sharpness and classify defocus versus motion blur.

    The classification is deliberately conservative: low absolute detail is required
    before a blur type is reported. Motion blur is directional, defocus is isotropic.
    """
    raw = raw_sharpness(gray)
    anisotropy = _gradient_anisotropy(gray)
    if raw >= 25.0:
        return SharpnessResult(raw=raw, blur_kind=BlurKind.NONE, blur_confidence=0.0)

    # Lower raw detail means more blur. The confidence ramps from 0 at 25 to 1 at 0.
    blur_amount = float(np.clip((25.0 - raw) / 25.0, 0.0, 1.0))
    if anisotropy >= 0.30:
        confidence = float(np.clip((anisotropy - 0.20) / 0.35, 0.0, 1.0)) * blur_amount
        return SharpnessResult(raw=raw, blur_kind=BlurKind.MOTION, blur_confidence=confidence)
    confidence = float(np.clip(1.0 - anisotropy / 0.30, 0.0, 1.0)) * blur_amount
    if confidence <= 0.05:
        return SharpnessResult(raw=raw, blur_kind=BlurKind.UNKNOWN, blur_confidence=0.0)
    return SharpnessResult(raw=raw, blur_kind=BlurKind.DEFOCUS, blur_confidence=confidence)
