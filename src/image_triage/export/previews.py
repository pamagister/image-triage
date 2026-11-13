"""WebP previews for selected photos."""

from __future__ import annotations

from pathlib import Path

from image_triage.core.models import Photo
from image_triage.core.settings import Settings
from image_triage.io.decode import decode_preview


def preview_path(photo: Photo, preview_dir: Path) -> Path:
    """Stable preview path derived from the photo digest."""
    digest = photo.digest or str(photo.id)
    return preview_dir / f"{digest}.webp"


def write_previews(photos: list[Photo], preview_dir: Path, settings: Settings) -> list[Path]:
    """Write WebP previews for selected photos into the central cache.

    Existing files are reused. Previews are keyed by content digest, so they are shared by
    every location of the same image and are never removed by exporting a subset.
    """
    preview_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for photo in photos:
        target = preview_path(photo, preview_dir)
        if target.exists():
            written.append(target)
            continue
        preview = decode_preview(
            photo.absolute_path,
            settings.report.preview_max_side,
            settings.analysis.draft,
        )
        preview.save(target, "WEBP", quality=settings.report.webp_quality, method=4)
        written.append(target)
    return written
