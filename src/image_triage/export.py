"""Copy or link selected images into the output folder."""

import os
import shutil
from logging import Logger
from pathlib import Path

from image_triage.scan import Photo

EXPORT_MODES = ["copy", "hardlink", "symlink"]


def export_photos(
    photos: list[Photo], input_root: Path, output_root: Path, mode: str, logger: Logger
) -> list[Path]:
    """Place each photo under `output_root`, keeping its path relative to `input_root`.

    Existing files in the output folder are left untouched.
    """
    exported = []
    for photo in photos:
        target = output_root / photo.path.relative_to(input_root)
        if target.exists():
            logger.debug(f"Skip existing {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "copy":
            shutil.copy2(photo.path, target)
        elif mode == "hardlink":
            os.link(photo.path, target)
        elif mode == "symlink":
            os.symlink(photo.path.resolve(), target)
        else:
            raise ValueError(f"Unknown export mode: {mode}")
        exported.append(target)
    logger.info(f"Exported {len(exported)} images to {output_root} ({mode})")
    return exported
