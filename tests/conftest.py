from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image


def _scene(seed: int) -> np.ndarray:
    """Random rectangles: a detailed, sharp test scene."""
    rng = np.random.default_rng(seed)
    img = np.full((600, 900, 3), 120, np.uint8)
    for _ in range(600):
        x, y = rng.integers(0, 850), rng.integers(0, 550)
        w, h = rng.integers(3, 40), rng.integers(3, 40)
        color = tuple(int(c) for c in rng.integers(20, 235, 3))
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), color, -1)
    return img


def save_jpeg(path: Path, pixels: np.ndarray, taken: datetime) -> Path:
    image = Image.fromarray(pixels)
    exif = image.getexif()
    exif.get_ifd(0x8769)[36867] = taken.strftime("%Y:%m:%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95, exif=exif)
    return path


@pytest.fixture
def photo_dir(tmp_path: Path) -> Path:
    """Burst of 3 shots of one scene (one blurry) + an unrelated scene."""
    scene = _scene(1)
    root = tmp_path / "in"
    save_jpeg(root / "burst_sharp.jpg", scene, datetime(2024, 1, 1, 20, 0, 0))
    save_jpeg(
        root / "burst_soft.jpg",
        cv2.GaussianBlur(scene, (0, 0), 0.6),
        datetime(2024, 1, 1, 20, 0, 1),
    )
    save_jpeg(
        root / "burst_blurry.jpg",
        cv2.GaussianBlur(scene, (0, 0), 6),
        datetime(2024, 1, 1, 20, 0, 2),
    )
    save_jpeg(root / "sub" / "other.jpg", _scene(2), datetime(2024, 1, 1, 20, 0, 3))
    return root
