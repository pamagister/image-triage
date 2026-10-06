"""Find image files and read capture timestamps."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

from image_triage.models import Detection

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng"}

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 36867
_SUBSEC_ORIGINAL = 37521
_DATETIME = 306
# Date and time in file names like "IMG_20150502_071410" or "2015-03-10 09.00.10".
_FILENAME_TIME = re.compile(
    r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})[ _-]?(\d{2})[.:_-]?(\d{2})[.:_-]?(\d{2})"
)


@dataclass
class Photo:
    """One analyzed image and the decisions made about it."""

    path: Path
    taken: datetime
    sharpness: float
    exposure: float
    phash: imagehash.ImageHash
    digest: str
    raw: Path | None = None
    objects: list[Detection] = field(default_factory=list)
    embedding: np.ndarray | None = None
    group: int = 0
    score: float = 0.0
    rating: int = 0
    best_in_group: bool = False
    selected: bool = False


def find_images(root: Path, exclude: Path | None = None) -> list[Path]:
    """Return all analyzable images below `root`, skipping the `exclude` directory."""
    exclude = exclude.resolve() if exclude else None
    files = []
    for path in root.rglob("*"):
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
            continue
        if exclude and path.resolve().is_relative_to(exclude):
            continue
        files.append(path)
    return sorted(files)


def find_raw_companion(image: Path) -> Path | None:
    """Return a RAW file with the same stem next to `image` (RAW+JPEG shooting)."""
    for sibling in image.parent.glob(image.stem + ".*"):
        if sibling.suffix.lower() in RAW_EXTENSIONS:
            return sibling
    return None


def capture_time(image: Image.Image, path: Path) -> datetime:
    """EXIF capture time (with sub-seconds), else time from the file name, else file mtime."""
    exif = image.getexif()
    sub = exif.get_ifd(_EXIF_IFD)
    raw = sub.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
    if raw:
        try:
            ts = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
            subsec = str(sub.get(_SUBSEC_ORIGINAL, "")).strip()
            if subsec.isdigit():
                ts = ts.replace(microsecond=int(float("0." + subsec) * 1_000_000))
            return ts
        except ValueError:
            pass
    if match := _FILENAME_TIME.search(path.stem):
        try:
            return datetime(*map(int, match.groups()))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)
