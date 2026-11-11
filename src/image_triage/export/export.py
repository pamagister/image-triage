"""Export selected originals without ever modifying the source files."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from image_triage.core.models import ExportMode, Photo


def export_photos(
    photos: list[Photo], input_root: Path, output_root: Path, mode: ExportMode
) -> list[Path]:
    """Copy or link selected photos into ``output_root``, preserving relative paths.

    Existing targets are left untouched so repeated runs are idempotent. Source files are
    only opened for reading (copy) or referenced by hard link/symlink.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    for photo in photos:
        target = output_root / photo.path
        if target.exists():
            exported.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = input_root / photo.path
        if mode is ExportMode.COPY:
            shutil.copy2(source, target)
        elif mode is ExportMode.HARDLINK:
            os.link(source, target)
        elif mode is ExportMode.SYMLINK:
            os.symlink(source.resolve(), target)
        else:  # pragma: no cover - guarded by the enum
            raise ValueError(f"unknown export mode: {mode}")
        exported.append(target)
    return exported
