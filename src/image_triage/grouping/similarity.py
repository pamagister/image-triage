"""Similarity grouping: duplicates, bursts and visually similar series."""

from __future__ import annotations

import imagehash
import numpy as np

from image_triage.core.models import Photo
from image_triage.core.settings import SimilaritySettings


def _hash(photo: Photo) -> imagehash.ImageHash | None:
    if not photo.phash:
        return None
    try:
        return imagehash.hex_to_hash(photo.phash)
    except (ValueError, TypeError):
        return None


def group_photos(photos: list[Photo], settings: SimilaritySettings) -> list[int]:
    """Return a deterministic 1-based group id for each input photo.

    Photos are grouped when they are byte-identical, or when they were captured close
    together and either their perceptual hashes are close or their YOLO embeddings are
    similar. Grouping is transitive (union-find) and group ids follow the chronological
    order of each group's first photo, with path as the final tie-break.
    """
    count = len(photos)
    if count == 0:
        return []
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    first_by_digest: dict[str, int] = {}
    for index, photo in enumerate(photos):
        first = first_by_digest.get(photo.digest)
        if first is None:
            first_by_digest[photo.digest] = index
        else:
            union(first, index)

    hashes = [_hash(photo) for photo in photos]
    embeddings = [
        np.asarray(photo.embedding, dtype=np.float32) if photo.embedding else None
        for photo in photos
    ]
    order = sorted(
        range(count),
        key=lambda index: (photos[index].taken or photos[index].path, photos[index].path),
    )
    for position, index in enumerate(order):
        current_time = photos[index].taken
        if current_time is None:
            continue
        for previous_index in reversed(order[:position]):
            previous_time = photos[previous_index].taken
            if previous_time is None:
                continue
            if (current_time - previous_time).total_seconds() > settings.max_time_gap_s:
                break
            similar = False
            current_hash, previous_hash = hashes[index], hashes[previous_index]
            if current_hash is not None and previous_hash is not None:
                similar = (current_hash - previous_hash) <= settings.max_hash_distance
            if not similar:
                current_embedding = embeddings[index]
                previous_embedding = embeddings[previous_index]
                if current_embedding is not None and previous_embedding is not None:
                    norms = float(np.linalg.norm(current_embedding)) * float(
                        np.linalg.norm(previous_embedding)
                    )
                    if norms > 1e-9:
                        similarity = float(current_embedding @ previous_embedding) / norms
                        similar = similarity >= settings.min_embedding_similarity
            if similar:
                union(index, previous_index)

    ids: dict[int, int] = {}
    for index in order:
        root = find(index)
        ids.setdefault(root, len(ids) + 1)
    return [ids[find(index)] for index in range(count)]
