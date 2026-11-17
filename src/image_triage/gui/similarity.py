"""Read-only, photo-relative visual suggestions based on stored perceptual hashes."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from heapq import nsmallest
from pathlib import PurePosixPath

from image_triage.core.models import Photo
from image_triage.db.repository import Repository


@dataclass(frozen=True, slots=True)
class SimilarMatch:
    """One available location and its distance from the current photo."""

    photo_id: int
    location_id: int
    path: str
    root: str
    distance: int
    identical: bool
    same_group: bool

    @property
    def key(self) -> tuple[int, int]:
        """Stable ordering by hash distance and then location identity."""
        return self.distance, self.location_id

    def to_dict(self) -> dict[str, object]:
        """Return the fields needed to render a suggestion."""
        return {
            "photo_id": self.photo_id,
            "location_id": self.location_id,
            "name": PurePosixPath(self.path).name,
            "path": self.path,
            "root": self.root,
            "distance": self.distance,
            "identical": self.identical,
            "same_group": self.same_group,
        }


def _hash_value(value: str) -> int | None:
    """Parse a standard 64-bit perceptual hash, rejecting missing or malformed data."""
    if len(value) != 16 or any(char not in "0123456789abcdefABCDEF" for char in value):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def find_similar(
    repo: Repository,
    photo: Photo,
    max_distance: int,
    *,
    roots: Sequence[str],
    after: tuple[int, int] | None = None,
    limit: int = 24,
) -> tuple[list[SimilarMatch], bool, bool]:
    """Find one page of matches without changing groups or loading the library into memory.

    ``after`` is the last result's (distance, location id) key. The final booleans indicate
    whether more matches exist and whether the source has a usable perceptual hash.
    """
    source_hash = _hash_value(photo.phash)

    def candidates() -> Iterator[SimilarMatch]:
        for row in repo.iter_similarity_candidates(photo.location_id, roots):
            identical = bool(photo.digest and row["digest"] == photo.digest)
            candidate_hash = _hash_value(row["phash"] or "")
            if identical:
                distance = 0
            elif source_hash is not None and candidate_hash is not None:
                distance = (source_hash ^ candidate_hash).bit_count()
            else:
                continue
            if distance > max_distance:
                continue
            match = SimilarMatch(
                photo_id=int(row["photo_id"]),
                location_id=int(row["location_id"]),
                path=row["path"],
                root=row["root"],
                distance=distance,
                identical=identical,
                same_group=photo.group_id is not None and row["group_id"] == photo.group_id,
            )
            if after is None or match.key > after:
                yield match

    matches = nsmallest(limit + 1, candidates(), key=lambda item: item.key)
    return matches[:limit], len(matches) > limit, source_hash is not None
