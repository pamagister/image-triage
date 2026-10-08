"""Read and write per-folder caches of reusable image analysis."""

from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import imagehash
import numpy as np
import yaml

from image_triage.models import Detection
from image_triage.scan import Photo, find_raw_companion

CACHE_FILENAME = ".image-triage.yaml"
CACHE_VERSION = 1


def read_folder_cache(folder: Path) -> dict[str, dict[str, object]]:
    path = folder / CACHE_FILENAME
    if not path.exists():
        return {}

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        raise ValueError(f"Invalid image-triage cache: {path}")
    photos = data.get("photos")
    if not isinstance(photos, dict) or not all(
        isinstance(name, str) and isinstance(entry, dict) for name, entry in photos.items()
    ):
        raise ValueError(f"Invalid photo entries in image-triage cache: {path}")
    return photos


def photo_from_cache(
    path: Path,
    digest: str,
    entry: dict[str, object] | None,
    detector_signature: str | None,
) -> Photo | None:
    if entry is None:
        return None
    if entry.get("digest") != digest or entry.get("detector_signature") != detector_signature:
        return None

    try:
        taken = datetime.fromisoformat(_string(entry, "taken"))
        sharpness = float(entry["sharpness"])
        exposure = float(entry["exposure"])
        phash = imagehash.hex_to_hash(_string(entry, "phash"))
        objects = [
            Detection(
                label=_string(obj, "label"),
                confidence=float(obj["confidence"]),
                box=tuple(float(value) for value in _number_list(obj, "box", 4)),
            )
            for obj in _mapping_list(entry, "objects")
        ]
        embedding_data = entry.get("embedding")
        if embedding_data is not None and (
            not isinstance(embedding_data, list)
            or not all(isinstance(value, (float, int)) for value in embedding_data)
        ):
            raise TypeError("Expected a list of numbers for embedding")
        embedding = (
            np.asarray(embedding_data, dtype=np.float32) if embedding_data is not None else None
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid cached analysis for {path.name}") from error

    return Photo(
        path=path,
        taken=taken,
        sharpness=sharpness,
        exposure=exposure,
        phash=phash,
        digest=digest,
        raw=find_raw_companion(path),
        objects=objects,
        embedding=embedding,
    )


def photo_record(photo: Photo, detector_signature: str | None) -> dict[str, object]:
    return {
        "digest": photo.digest,
        "detector_signature": detector_signature,
        "taken": photo.taken.isoformat(),
        "sharpness": photo.sharpness,
        "exposure": photo.exposure,
        "phash": str(photo.phash),
        "objects": [
            {"label": obj.label, "confidence": obj.confidence, "box": list(obj.box)}
            for obj in photo.objects
        ],
        "embedding": photo.embedding.tolist() if photo.embedding is not None else None,
    }


def write_folder_cache(folder: Path, photos: dict[str, dict[str, object]]) -> None:
    path = folder / CACHE_FILENAME
    data = {"version": CACHE_VERSION, "photos": photos}
    serialized = yaml.safe_dump(data, sort_keys=True, allow_unicode=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=folder,
        prefix=f"{CACHE_FILENAME}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(serialized)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _string(entry: dict[str, object], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str):
        raise TypeError(f"Expected a string for {key}")
    return value


def _mapping_list(entry: dict[str, object], key: str) -> list[dict[str, object]]:
    value = entry[key]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"Expected a list of mappings for {key}")
    return value


def _number_list(entry: dict[str, object], key: str, length: int) -> list[float]:
    value = entry[key]
    if (
        not isinstance(value, list)
        or len(value) != length
        or not all(isinstance(item, (float, int)) for item in value)
    ):
        raise TypeError(f"Expected {length} numbers for {key}")
    return value
