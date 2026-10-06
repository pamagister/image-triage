"""Write XMP star ratings and object keywords with ExifTool."""

import shutil
import subprocess
from logging import Logger
from pathlib import Path

from image_triage.scan import Photo

INSTALL_HINT = (
    "Install ExifTool (Windows: 'winget install OliverBetz.ExifTool', "
    "Debian/Ubuntu: 'sudo apt install libimage-exiftool-perl') or set "
    "metadata.exiftool_path, or disable metadata.write_xmp_rating and metadata.write_keywords."
)


def find_exiftool(configured: str) -> str | None:
    """Return a usable exiftool executable path or None."""
    if Path(configured).is_file():
        return configured
    return shutil.which(configured)


def _tags(photo: Photo, write_rating: bool, write_keywords: bool) -> list[str]:
    tags = [f"-XMP-xmp:Rating={photo.rating}"] if write_rating else []
    if write_keywords:
        for label in sorted({d.label for d in photo.objects}):
            # Remove first, then add: no duplicates, other keywords are kept.
            tags += [f"-XMP-dc:Subject-={label}", f"-XMP-dc:Subject+={label}"]
    return tags


def _commands(
    photos: list[Photo], sidecar_for_raw: bool, write_rating: bool, write_keywords: bool
) -> list[list[str]]:
    commands = []
    for photo in photos:
        tags = _tags(photo, write_rating, write_keywords)
        if not tags:
            continue
        commands.append([*tags, str(photo.path)])
        if sidecar_for_raw and photo.raw:
            sidecar = photo.raw.with_suffix(".xmp")
            if sidecar.exists():
                commands.append([*tags, str(sidecar)])
            else:
                # Create the sidecar from the RAW file's metadata.
                commands.append([*tags, "-o", str(sidecar), str(photo.raw)])
    return commands


def write_metadata(
    photos: list[Photo],
    exiftool: str,
    sidecar_for_raw: bool,
    write_rating: bool,
    write_keywords: bool,
    logger: Logger,
) -> None:
    """Write `photo.rating` as XMP Rating and/or detected objects as XMP keywords (dc:subject)
    into each file (and RAW sidecars) in one ExifTool run."""
    commands = _commands(photos, sidecar_for_raw, write_rating, write_keywords)
    if not commands:
        return
    argfile = "\n".join("\n".join(cmd) + "\n-execute" for cmd in commands) + "\n"
    result = subprocess.run(
        [
            exiftool,
            "-@",
            "-",
            "-common_args",
            "-charset",
            "filename=utf8",
            "-overwrite_original",
            "-P",
        ],
        input=argfile.encode("utf-8"),
        capture_output=True,
    )
    for line in result.stderr.decode("utf-8", "replace").splitlines():
        if line.strip():
            logger.warning(f"exiftool: {line.strip()}")
    if result.returncode != 0:
        raise RuntimeError(f"exiftool failed with exit code {result.returncode}")
    logger.info(f"Wrote XMP metadata for {len(photos)} images ({len(commands)} files)")
