"""Detect whether a photo library is empty, current or stale across all roots.

The check is advisory: it compares the files on disk with the mtime recorded by the last
scan. A full scan still recomputes digests, so a change that preserves mtime is only picked
up by an explicit scan. Locations migrated from the legacy single-root schema have no stored
mtime and fall back to their analysis timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from image_triage.analysis.analyze import scan_plan
from image_triage.core.settings import Settings
from image_triage.db.repository import Repository


@dataclass(slots=True)
class LibraryStatus:
    """Counts describing how far the stored state is from the files on disk."""

    roots: list[str] = field(default_factory=list)
    files: int = 0
    stored: int = 0
    new: int = 0
    missing: int = 0
    changed: int = 0
    unavailable: int = 0

    @property
    def root(self) -> str:
        return self.roots[0] if self.roots else ""

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
            "roots": list(self.roots),
            "files": self.files,
            "stored": self.stored,
            "new": self.new,
            "missing": self.missing,
            "changed": self.changed,
            "unavailable": self.unavailable,
            "empty": self.empty,
            "stale": self.stale,
            "current": self.current,
        }


def _analyzed_at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def library_status(settings: Settings, repository: Repository) -> LibraryStatus:
    """Compare the files on disk with the analyzed locations in the state database."""
    plan = scan_plan(settings)
    files = {
        (str(root), path.relative_to(root).as_posix()) for root, paths in plan for path in paths
    }
    stored_map = repository.location_paths(available_only=False)
    known = set(stored_map)
    available = {key for key, value in stored_map.items() if value["available"]}
    changed: set[tuple[str, str]] = set()
    for key in files & known:
        value = stored_map[key]
        if not value["available"]:
            changed.add(key)
            continue
        root, relative = key
        try:
            modified = datetime.fromtimestamp((Path(root) / relative).stat().st_mtime)
        except OSError:
            continue
        stored_mtime = value["mtime"]
        if stored_mtime is None:
            analyzed_at = _analyzed_at(value["analyzed_at"])
            if analyzed_at is None:
                changed.add(key)
                continue
            reference = analyzed_at.timestamp()
        else:
            reference = float(stored_mtime)
        if abs(modified.timestamp() - reference) > 1.0:
            changed.add(key)
    missing = {key for key in known - files if stored_map[key]["available"]}
    return LibraryStatus(
        roots=[str(root) for root, _paths in plan],
        files=len(files),
        stored=len(available),
        new=len(files - known),
        missing=len(missing),
        changed=len(changed),
        unavailable=sum(1 for value in stored_map.values() if not value["available"]),
    )
