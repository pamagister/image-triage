"""Export selected originals without ever modifying the source files."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image, ImageOps

from image_triage.core.models import ExportMode, Photo
from image_triage.io.scan import RAW_EXTENSIONS

_RERENDER_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def _source(photo: Photo, input_root: Path) -> Path:
    """Original file path for a photo, using its stored location when known."""
    if photo.root_path:
        return Path(photo.root_path) / photo.path
    return input_root / photo.path


def _flat_target(output_root: Path, source_name: str, used: set[str]) -> Path:
    """Deterministic, collision-free flat target using ``name_1`` suffixes."""
    stem = Path(source_name).stem
    suffix = Path(source_name).suffix
    candidate = source_name
    index = 1
    while candidate in used:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used.add(candidate)
    return output_root / candidate


def _tree_target(output_root: Path, relative: str, root_path: str, used: set[str]) -> Path:
    """Reconstruct the relative folder tree; disambiguate identical relative paths."""
    relative_path = Path(relative)
    parts = relative_path.parts
    if len(parts) > 1 and len({root_path}) > 0:
        # Two roots can contain the same relative path. Prefer the relative tree and only
        # disambiguate when a collision actually occurs.
        pass
    candidate = relative_path.as_posix()
    if candidate in used:
        stem = relative_path.stem
        suffix = relative_path.suffix
        parent = relative_path.parent.as_posix()
        index = 1
        while True:
            name = f"{stem}_{index}{suffix}"
            candidate = f"{parent}/{name}" if parent not in {"", "."} else name
            if candidate not in used:
                break
            index += 1
    used.add(candidate)
    return output_root / candidate


def _rerender(source: Path, target: Path, max_long_edge: int | None, quality: int) -> None:
    """Write a JPEG re-render, preserving EXIF and ICC and applying orientation."""
    with Image.open(source) as image:
        exif = image.info.get("exif")
        icc = image.info.get("icc_profile")
        image = ImageOps.exif_transpose(image)
        if max_long_edge is not None:
            image.thumbnail((max_long_edge, max_long_edge), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        target.parent.mkdir(parents=True, exist_ok=True)
        save_kwargs = {"quality": quality, "optimize": True}
        if exif:
            save_kwargs["exif"] = exif
        if icc:
            save_kwargs["icc_profile"] = icc
        image.save(target, "JPEG", **save_kwargs)


def export_photos(
    photos: list[Photo],
    input_root: Path,
    output_root: Path,
    mode: ExportMode,
    *,
    layout: str = "flat",
    rerender: bool = False,
    max_long_edge: int | None = None,
    jpeg_quality: int = 85,
) -> list[Path]:
    """Copy or link selected photos into ``output_root``.

    Flat layout writes one directory and resolves file-name collisions with ``_1``,
    ``_2`` suffixes. Tree layout reconstructs each location's relative path. Re-rendering
    forces copy mode because a link cannot point at newly rendered pixels. RAW files are
    never re-rendered.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    used_flat: set[str] = set()
    used_tree: set[str] = set()
    for photo in sorted(photos, key=lambda item: (item.root_path, item.path)):
        source = _source(photo, input_root)
        if layout == "tree":
            target = _tree_target(output_root, photo.path, photo.root_path, used_tree)
        else:
            target = _flat_target(output_root, Path(photo.path).name, used_flat)
        if target.exists():
            exported.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        render = rerender and source.suffix.lower() not in RAW_EXTENSIONS
        if render:
            if target.suffix.lower() != ".jpg":
                target = target.with_suffix(".jpg")
            if target.exists():
                exported.append(target)
                continue
            _rerender(source, target, max_long_edge, jpeg_quality)
        elif mode is ExportMode.COPY:
            shutil.copy2(source, target)
        elif mode is ExportMode.HARDLINK:
            os.link(source, target)
        elif mode is ExportMode.SYMLINK:
            os.symlink(source.resolve(), target)
        else:  # pragma: no cover - guarded by the enum
            raise ValueError(f"unknown export mode: {mode}")
        exported.append(target)
    return exported
