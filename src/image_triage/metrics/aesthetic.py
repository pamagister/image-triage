"""Learned aesthetic scoring with a deterministic heuristic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODEL_INPUT_SIZE = 224
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass(slots=True)
class AestheticResult:
    """Aesthetic score in 0..1 and where it came from."""

    score: float
    source: str


def heuristic_aesthetic(gray: np.ndarray, sharpness: float, rgb: np.ndarray | None = None) -> float:
    """Interest proxy from colorfulness, contrast, brightness and detail.

    This is used when no aesthetic ONNX model is installed. It is intentionally simple
    and deterministic; it never claims to be a learned aesthetic judgment.
    """
    gray_f = gray.astype(np.float32)
    contrast = float(gray_f.std()) / 64.0
    mean = float(gray_f.mean()) / 255.0
    brightness = 1.0 - min(1.0, abs(mean - 0.5) / 0.5)
    detail = float(np.clip(sharpness / 0.6, 0.0, 1.0))

    colorfulness = 0.0
    if rgb is not None and rgb.ndim == 3:
        r, g, b = cv2.split(rgb.astype(np.float32))
        rg = r - g
        yb = 0.5 * (r + g) - b
        colorfulness = float(np.clip((np.std(rg) + np.std(yb)) / 80.0, 0.0, 1.0))
    score = 0.35 * float(np.clip(contrast, 0, 1)) + 0.25 * brightness + 0.2 * detail
    score += 0.2 * colorfulness
    return float(np.clip(score, 0.0, 1.0))


def _preprocess(image: Image.Image, size: int) -> np.ndarray:
    resized = image.convert("RGB").resize((size, size), Image.Resampling.BILINEAR)
    array = np.asarray(resized, dtype=np.float32) / 255.0
    array = (array - IMAGENET_MEAN) / IMAGENET_STD
    return array.transpose(2, 0, 1)[None]


def _model_score(outputs: list[np.ndarray]) -> float:
    values = np.asarray(outputs[0], dtype=np.float64)
    if values.ndim == 2 and values.shape[1] == 10:
        probabilities = np.clip(values[0], 0.0, None)
        probabilities = probabilities / max(1e-9, probabilities.sum())
        return float(np.dot(np.arange(1, 11), probabilities) / 10.0)
    if values.size == 1:
        return float(values.reshape(-1)[0])
    return float(np.clip(values.mean(), 0.0, 1.0))


def aesthetic_score(
    image: Image.Image,
    gray: np.ndarray,
    sharpness: float,
    model_path: Path | None = None,
) -> AestheticResult:
    """Score aesthetics with an ONNX model when available, else a heuristic.

    The ONNX output is calibrated to 0..1: single-output models are clamped, and
    10-class NIMA-style distributions are converted to their expected value / 10.
    """
    if model_path is not None and model_path.is_file():
        try:
            import onnxruntime as ort

            session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
            input_name = session.get_inputs()[0].name
            outputs = session.run(None, {input_name: _preprocess(image, MODEL_INPUT_SIZE)})
            return AestheticResult(score=float(np.clip(_model_score(outputs), 0, 1)), source="onnx")
        except Exception:
            # A broken or unsupported model must not block analysis.
            pass
    return AestheticResult(
        score=heuristic_aesthetic(gray, sharpness, np.asarray(image, dtype=np.uint8)),
        source="heuristic",
    )
