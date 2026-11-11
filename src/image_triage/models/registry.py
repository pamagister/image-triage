"""Model registry: descriptors, checksum-verified downloads and installed-model metadata."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from image_triage.core.errors import ModelError, UsageError
from image_triage.core.settings import Settings

REGISTRY_PATH = Path("res/models/registry.json")
YOLO_URL = (
    "https://raw.githubusercontent.com/pamagister/Photo-Composition-Designer/"
    "main/res/yolo/yolo26n.onnx"
)
YOLO_SHA256 = "c081e98157a0c0ba08fbed26a478d9caaf34e6b7bcc50d396f50e2c0d508a615"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Static description of a supported model."""

    name: str
    filename: str
    description: str
    license: str
    license_url: str
    url: str | None
    sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MODELS: dict[str, ModelSpec] = {
    "yolo": ModelSpec(
        name="yolo",
        filename="yolo26n.onnx",
        description="YOLO26 nano object detector and content-embedding backbone.",
        license="AGPL-3.0",
        license_url="https://github.com/ultralytics/ultralytics/blob/main/LICENSE",
        url=YOLO_URL,
        sha256=YOLO_SHA256,
    ),
    "aesthetic": ModelSpec(
        name="aesthetic",
        filename="aesthetic.onnx",
        description=(
            "Optional NIMA-style aesthetic CNN. No centrally hosted, license-verified "
            "download is bundled; install a local ONNX file explicitly."
        ),
        license="model-specific",
        license_url="",
        url=None,
        sha256=None,
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registry_path(settings: Settings) -> Path:
    return Path(settings.models.registry_path).expanduser().resolve()


def _read_registry(settings: Settings) -> dict[str, Any]:
    path = _registry_path(settings)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_registry(settings: Settings, registry: dict[str, Any]) -> None:
    path = _registry_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _target_path(settings: Settings, spec: ModelSpec) -> Path:
    if spec.name == "yolo":
        return settings.models.yolo_path
    return settings.models.aesthetic_path


def download_model(
    url: str,
    target: Path,
    sha256: str,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Download a model to ``target`` and verify its SHA256 checksum."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            for chunk in iter(lambda: response.read(1 << 16), b""):
                handle.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise ModelError(
            f"checksum mismatch for {url}",
            expected=sha256,
            actual=digest.hexdigest(),
        )
    os.replace(part, target)


def install_model(
    settings: Settings,
    name: str,
    *,
    path: Path | None = None,
    sha256: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Install a model and record its checksum and license.

    ``yolo`` downloads from the registered URL unless ``path`` is supplied. ``aesthetic``
    requires a local ``path`` because no license-verified remote download is bundled.
    """
    spec = MODELS.get(name)
    if spec is None:
        raise UsageError(f"unknown model: {name}", available=sorted(MODELS))
    target = _target_path(settings, spec)
    if target.exists() and not force:
        raise ModelError(f"{target} already exists; use --force to replace it", path=str(target))

    if path is not None:
        if not path.is_file():
            raise ModelError(f"local model file not found: {path}", path=str(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        actual = _sha256(target)
        if sha256 is not None and actual != sha256:
            target.unlink(missing_ok=True)
            raise ModelError("checksum mismatch", expected=sha256, actual=actual)
    elif spec.url and spec.sha256:
        download_model(spec.url, target, spec.sha256)
        actual = spec.sha256
    else:
        raise ModelError(
            f"no remote download is registered for {name}; install a local ONNX file with --path"
        )

    registry = _read_registry(settings)
    registry[name] = {
        "path": str(target),
        "sha256": actual,
        "license": spec.license,
        "license_url": spec.license_url,
        "source": spec.url or str(path),
        "installed_at": datetime.now(UTC).isoformat(),
    }
    _write_registry(settings, registry)
    return registry[name]


def list_models(settings: Settings) -> list[dict[str, Any]]:
    """Return registry metadata and installed status for every known model."""
    registry = _read_registry(settings)
    entries = []
    for name, spec in MODELS.items():
        target = _target_path(settings, spec)
        installed = target.is_file()
        entry = spec.to_dict()
        entry.update(
            {
                "path": str(target),
                "installed": installed,
                "installed_sha256": _sha256(target) if installed else None,
                "registry": registry.get(name),
            }
        )
        entries.append(entry)
    return entries


def main() -> int:
    """Entry point for ``image-triage-download-model`` (YOLO by default)."""
    from image_triage.core.settings import load_settings

    name = sys.argv[1] if len(sys.argv) > 1 else "yolo"
    settings = load_settings()
    try:
        entry = install_model(settings, name)
    except (ModelError, UsageError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"installed {name}: {entry['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
