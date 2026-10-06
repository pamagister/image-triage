"""Pick the N most relevant photos: spread over events, one per motif, diverse in content."""

from collections import defaultdict
from pathlib import Path

import numpy as np

from image_triage.scan import Photo


def event_quotas(sizes: dict[Path, int], top_n: int) -> dict[Path, int]:
    """Split `top_n` places over events proportionally to their number of candidates.

    Every event gets at least one place if there are enough places (Sainte-Laguë method,
    capped at the event size).
    """
    quotas = dict.fromkeys(sizes, 0)
    if top_n >= len(sizes):
        quotas = {event: min(1, size) for event, size in sizes.items()}
    for _ in range(top_n - sum(quotas.values())):
        open_events = [e for e in sizes if quotas[e] < sizes[e]]
        if not open_events:
            break
        event = max(open_events, key=lambda e: sizes[e] / (2 * quotas[e] + 1))
        quotas[event] += 1
    return quotas


def _centered(photos: list[Photo]) -> dict[int, np.ndarray]:
    """Mean-centered, normalized embeddings, so that cosine similarities spread over [-1, 1]."""
    with_embedding = [p for p in photos if p.embedding is not None]
    if not with_embedding:
        return {}
    matrix = np.array([p.embedding for p in with_embedding])
    matrix -= matrix.mean(axis=0)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 1e-9)
    return {id(p): v for p, v in zip(with_embedding, matrix)}


def pick_diverse(
    candidates: list[Photo], count: int, diversity: float, vectors: dict[int, np.ndarray]
) -> list[Photo]:
    """Greedy maximal marginal relevance: high score, but unlike the photos already picked."""
    remaining = sorted(candidates, key=lambda p: (-p.score, p.path))
    chosen: list[Photo] = []

    def value(photo: Photo) -> float:
        vec = vectors.get(id(photo))
        if vec is None:
            return photo.score
        sims = [float(vec @ vectors[id(c)]) for c in chosen if id(c) in vectors]
        return photo.score - diversity * max([0.0, *sims])

    while remaining and len(chosen) < count:
        best = max(remaining, key=value)
        remaining.remove(best)
        chosen.append(best)
    return chosen


def select_top(photos: list[Photo], top_n: int, diversity: float) -> list[Photo]:
    """Return up to `top_n` photos: the best of each similarity group, spread over all folders.

    Each folder containing photos counts as one event (holiday, party, ...).
    """
    candidates = [p for p in photos if p.best_in_group]
    events: dict[Path, list[Photo]] = defaultdict(list)
    for photo in sorted(candidates, key=lambda p: p.path):
        events[photo.path.parent].append(photo)

    quotas = event_quotas({e: len(members) for e, members in events.items()}, top_n)
    vectors = _centered(candidates)
    selected = []
    for event, members in events.items():
        selected += pick_diverse(members, quotas[event], diversity, vectors)
    return selected
