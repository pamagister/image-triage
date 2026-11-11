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


def write_previews(
    photos: list[Photo], input_root: Path, preview_dir: Path, settings: Settings
) -> list[Path]:
    """Write WebP previews for selected photos, skipping existing files."""
    preview_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for photo in photos:
        target = preview_path(photo, preview_dir)
        if target.exists():
            written.append(target)
            continue
        preview = decode_preview(
            input_root / photo.path,
            settings.report.preview_max_side,
            settings.analysis.draft,
        )
        preview.save(target, "WEBP", quality=settings.report.webp_quality, method=4)
        written.append(target)
    return written
