"""Detect whether a photo library is empty, current or stale.

The check is deliberately advisory: it compares stored paths and file mtimes against the
analysis timestamp. A full scan still recomputes digests, so a change that preserves mtime
is only picked up by an explicit scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from image_triage.core.settings import Settings
from image_triage.db.repository import Repository
from image_triage.io.scan import find_images


@dataclass(slots=True)
class LibraryStatus:
    """Counts describing how far the stored state is from the files on disk."""

    root: str
    files: int = 0
    stored: int = 0
    new: int = 0
    missing: int = 0
    changed: int = 0

    @property
    def empty(self) -> bool:
        return self.stored == 0 and self.files > 0

    @property
    def stale(self) -> bool:
        return self.new > 0 or self.missing > 0 or self.changed > 0

    @property
    def current(self) -> bool:
        return self.stored > 0 and not self.stale

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": self.files,
            "stored": self.stored,
            "new": self.new,
            "missing": self.missing,
            "changed": self.changed,
            "empty": self.empty,
            "stale": self.stale,
            "current": self.current,
        }


def scan_paths(settings: Settings) -> tuple[Path, list[Path]]:
    """Resolve the library root and the analyzable files below it."""
    root = Path(settings.input.root).expanduser().resolve()
    if not root.is_dir():
        return root, []
    exclude = [root / ".image-triage"]
    exclude.extend(root / name for name in settings.input.exclude)
    return root, find_images(root, tuple(exclude))


def _analyzed_at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def library_status(settings: Settings, repository: Repository) -> LibraryStatus:
    """Compare the files on disk with the analyzed photos in the state database."""
    root, paths = scan_paths(settings)
    stored = repository.analyzed_paths()
    files = {path.relative_to(root).as_posix() for path in paths}

    new = files - stored.keys()
    missing = stored.keys() - files
    changed = set()
    for relative in files & stored.keys():
        analyzed_at = _analyzed_at(stored[relative])
        if analyzed_at is None:
            changed.add(relative)
            continue
        try:
            modified = datetime.fromtimestamp((root / relative).stat().st_mtime)
        except OSError:
            continue
        # Compare with a small tolerance so a rewritten-but-equally-timestamped file is not
        # reported as changed on every check.
        if modified.timestamp() > analyzed_at.timestamp() + 1.0:
            changed.add(relative)

    return LibraryStatus(
        root=str(root),
        files=len(files),
        stored=len(stored),
        new=len(new),
        missing=len(missing),
        changed=len(changed),
    )
