"""Group exact duplicates and visually similar shots taken close together."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import blake3
import imagehash
import numpy as np
from PIL import Image


def file_digest(path: Path) -> str:
    """BLAKE3 hash of the file content (detects exact duplicates)."""
    hasher = blake3.blake3()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def perceptual_hash(image: Image.Image) -> imagehash.ImageHash:
    return imagehash.phash(image)


def group_similar(
    times: Sequence[datetime],
    hashes: Sequence[imagehash.ImageHash],
    digests: Sequence[str],
    max_distance: int,
    max_time_gap_s: float,
    embeddings: Sequence[np.ndarray | None] | None = None,
    min_embedding_similarity: float = 1.0,
) -> list[int]:
    """Return a group id per image.

    Two images end up in the same group if their files are identical, or if
    they were taken at most `max_time_gap_s` apart and either their perceptual
    hashes differ by at most `max_distance` bits or their content embeddings
    have a cosine similarity of at least `min_embedding_similarity`.
    Groups are transitive.
    """

    def similar(i: int, j: int) -> bool:
        if hashes[i] - hashes[j] <= max_distance:
            return True
        if embeddings is None or embeddings[i] is None or embeddings[j] is None:
            return False
        return float(embeddings[i] @ embeddings[j]) >= min_embedding_similarity

    parent = list(range(len(times)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    first_by_digest: dict[str, int] = {}
    for i, digest in enumerate(digests):
        if digest in first_by_digest:
            union(i, first_by_digest[digest])
        else:
            first_by_digest[digest] = i

    order = sorted(range(len(times)), key=lambda i: times[i])
    for pos, i in enumerate(order):
        for j in reversed(order[:pos]):
            if (times[i] - times[j]).total_seconds() > max_time_gap_s:
                break
            if similar(i, j):
                union(i, j)

    # Number groups in chronological order of their first image.
    ids: dict[int, int] = {}
    for i in order:
        ids.setdefault(find(i), len(ids) + 1)
    return [ids[find(i)] for i in range(len(times))]
