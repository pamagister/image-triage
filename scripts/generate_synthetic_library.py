"""Generate a deterministic synthetic photo library for scale tests."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def _scene(seed: int, width: int, height: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = np.full((height, width, 3), int(rng.integers(40, 200)), np.uint8)
    for _ in range(max(20, width * height // 200)):
        x, y = int(rng.integers(0, width - 2)), int(rng.integers(0, height - 2))
        w, h = int(rng.integers(2, max(3, width // 8))), int(rng.integers(2, max(3, height // 8)))
        color = tuple(int(value) for value in rng.integers(0, 255, 3))
        cv2.rectangle(image, (x, y), (x + w, y + h), color, -1)
    if seed % 17 == 0:
        image = cv2.GaussianBlur(image, (0, 0), 2.0)
    return image


def generate(root: Path, count: int, width: int = 160, height: int = 120) -> None:
    """Write ``count`` JPEGs with capture times spread over 300 event days."""
    root.mkdir(parents=True, exist_ok=True)
    start = datetime(2024, 1, 1, 8, 0, 0)
    for index in range(count):
        day, slot = divmod(index, 20)
        taken = start + timedelta(days=day, minutes=7 * slot)
        image = Image.fromarray(_scene(index, width, height))
        exif = image.getexif()
        exif.get_ifd(0x8769)[36867] = taken.strftime("%Y:%m:%d %H:%M:%S")
        path = root / f"{day:03d}_{slot:02d}_{index:04d}.jpg"
        image.save(path, quality=72, exif=exif)
        if index % 1000 == 0:
            print(f"generated {index}/{count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--count", type=int, default=6000)
    parser.add_argument("--width", type=int, default=160)
    parser.add_argument("--height", type=int, default=120)
    args = parser.parse_args()
    generate(args.root, args.count, args.width, args.height)
    print(f"generated {args.count} images in {args.root}")


if __name__ == "__main__":
    main()
