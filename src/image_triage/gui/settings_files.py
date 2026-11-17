"""Stage settings files together and roll back ordinary save failures."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _stage(path: Path, contents: bytes) -> Path:
    """Write a private temporary file on the same filesystem as its destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


@contextmanager
def replace_settings_files(files: dict[Path, str]) -> Iterator[None]:
    """Replace settings files, restoring originals if a write or subsequent operation fails.

    Each replacement is atomic. Rollback also covers exceptions raised inside the context;
    it cannot guarantee a multi-file transaction across an abrupt process or system crash.
    """
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    replaced: list[Path] = []
    preserved: set[Path] = set()
    try:
        for path, text in files.items():
            staged[path] = _stage(path, text.encode("utf-8"))
            backups[path] = _stage(path, path.read_bytes()) if path.exists() else None
        for path, temporary in staged.items():
            os.replace(temporary, path)
            replaced.append(path)
        yield
    except BaseException as original:
        errors = []
        for path in reversed(replaced):
            backup = backups[path]
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(backup, path)
            except OSError as exc:
                if backup is not None:
                    preserved.add(backup)
                errors.append(f"{path}: {exc}; backup: {backup}")
        if errors:
            raise RuntimeError("settings rollback failed: " + "; ".join(errors)) from original
        raise
    finally:
        for path in [*staged.values(), *(item for item in backups.values() if item is not None)]:
            if path not in preserved:
                path.unlink(missing_ok=True)
