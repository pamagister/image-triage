"""Recursive image scan: EXIF capture time, GPS, dimensions and file digest."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import blake3
from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng"}

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 36867
_SUBSEC_ORIGINAL = 37521
_DATETIME = 306
_GPS_IFD = 34853
_FILENAME_TIME = re.compile(
    r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})[ _-]?(\d{2})[.:_-]?(\d{2})[.:_-]?(\d{2})"
)


@dataclass(slots=True)
class ScanInfo:
    """Metadata read from an image header without decoding pixels."""

    path: Path
    taken: datetime
    width: int
    height: int
    camera_make: str | None = None
    camera_model: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None


def file_digest(path: Path) -> str:
    """BLAKE3 digest of the file content, used for duplicate detection."""
    hasher = blake3.blake3()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _rational(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value[0]) / float(value[1])
    except (TypeError, ZeroDivisionError, IndexError, ValueError):
        return 0.0


def _dms_to_degrees(values: object) -> float:
    try:
        degrees, minutes, seconds = (_rational(v) for v in values)  # type: ignore[misc]
    except TypeError:
        return 0.0
    return degrees + minutes / 60.0 + seconds / 3600.0


def _gps_decimal(gps: object) -> tuple[float | None, float | None]:
    if not isinstance(gps, dict):
        return None, None
    lat = _dms_to_degrees(gps.get(2, (0, 0, 0)))
    lon = _dms_to_degrees(gps.get(4, (0, 0, 0)))
    if gps.get(1) in {"S", "W"}:
        lat = -lat
    if gps.get(3) in {"S", "W"}:
        lon = -lon
    if lat == 0.0 and lon == 0.0:
        return None, None
    return lat, lon


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def capture_time(image: Image.Image, path: Path) -> datetime:
    """EXIF capture time with sub-seconds, else filename time, else file mtime."""
    exif = image.getexif()
    sub_ifd = exif.get_ifd(_EXIF_IFD)
    parsed = _parse_time(sub_ifd.get(_DATETIME_ORIGINAL)) or _parse_time(exif.get(_DATETIME))
    if parsed:
        subsec = str(sub_ifd.get(_SUBSEC_ORIGINAL, "")).strip()
        if subsec.isdigit():
            parsed = parsed.replace(microsecond=int(float("0." + subsec) * 1_000_000))
        return parsed
    if match := _FILENAME_TIME.search(path.stem):
        try:
            return datetime(*map(int, match.groups()))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def scan_file(path: Path) -> ScanInfo:
    """Read header metadata and GPS from one image."""
    with Image.open(path) as image:
        taken = capture_time(image, path)
        exif = image.getexif()
        gps = exif.get_ifd(_GPS_IFD)
        gps_lat, gps_lon = _gps_decimal(gps)
        width, height = ImageOps.exif_transpose(image).size
        return ScanInfo(
            path=path,
            taken=taken,
            width=int(width),
            height=int(height),
            camera_make=(exif.get(271) or None),
            camera_model=(exif.get(272) or None),
            gps_lat=gps_lat,
            gps_lon=gps_lon,
        )


def find_images(root: Path, exclude: tuple[Path, ...] = ()) -> list[Path]:
    """Return analyzable images below ``root``, sorted deterministically."""
    resolved_exclude = tuple(path.resolve() for path in exclude)
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if any(resolved.is_relative_to(excluded) for excluded in resolved_exclude):
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix())


def find_raw_companion(image: Path) -> Path | None:
    """Return a RAW sibling with the same stem (RAW+JPEG shooting)."""
    for sibling in image.parent.glob(image.stem + ".*"):
        if sibling.suffix.lower() in RAW_EXTENSIONS:
            return sibling
    return None
