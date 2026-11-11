"""Robust image decoding to a bounded RGB preview."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def decode_preview(path: Path, max_side: int = 1024, draft: bool = True) -> Image.Image:
    """Decode an image to an RGB thumbnail no larger than ``max_side``.

    JPEG draft mode decodes at a reduced resolution when possible. EXIF orientation is
    applied before resizing. Corrupt or unsupported files raise an exception; the caller
    is responsible for collecting per-file errors.

    Args:
        path: Image file.
        max_side: Maximum width/height of the returned image in pixels.
        draft: Enable JPEG draft decoding.

    Raises:
        OSError: The file cannot be decoded.
    """
    with Image.open(path) as image:
        if draft and image.format == "JPEG":
            image.draft("RGB", (max_side, max_side))
        image = ImageOps.exif_transpose(image)
        preview = image.convert("RGB")
    preview.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return preview


def grayscale(preview: Image.Image):
    """Return a grayscale copy of a preview."""
    return preview.convert("L")
