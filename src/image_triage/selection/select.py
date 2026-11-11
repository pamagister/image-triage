"""Deterministic quota-aware MMR selection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from image_triage.core.models import Photo
from image_triage.selection.profiles import SelectionProfile


@dataclass(slots=True)
class SelectedPhoto:
    """One selected photo with its rank and explanation."""

    photo: Photo
    rank: int
    score: float
    reason: str
    quota_rule: str


def _event_id(photo: Photo) -> int:
    return photo.event_id if photo.event_id is not None else 0


def _day(photo: Photo) -> str:
    return photo.taken.date().isoformat() if photo.taken else "unknown"


def _cluster_id(photo: Photo) -> int:
    return photo.group_id if photo.group_id is not None else 0


def best_per_group(photos: list[Photo]) -> list[Photo]:
    """Return the best photo of each similarity group."""
    grouped: dict[int, list[Photo]] = defaultdict(list)
    for photo in photos:
        grouped[photo.group_id or 0].append(photo)
    best = []
    for members in grouped.values():
        best.append(
            min(
                members,
                key=lambda photo: (
                    -photo.score,
                    photo.taken or datetime.max,
                    photo.path,
                ),
            )
        )
    return sorted(best, key=lambda photo: (photo.taken or datetime.max, photo.path))


def event_quotas(sizes: dict[int, int], top_n: int, rule: str = "sainte_lague") -> dict[int, int]:
    """Split ``top_n`` places over events without exceeding event sizes."""
    quotas = dict.fromkeys(sizes, 0)
    if top_n <= 0 or not sizes:
        return quotas
    if rule == "equal":
        events = sorted(sizes)
        while sum(quotas.values()) < top_n:
            open_events = [event for event in events if quotas[event] < sizes[event]]
            if not open_events:
                break
            for event in open_events:
                if sum(quotas.values()) >= top_n:
                    break
                quotas[event] += 1
        return quotas
    if rule == "proportional":
        total = sum(sizes.values())
        remainders: list[tuple[float, int]] = []
        for event, size in sizes.items():
            exact = size / total * top_n
            quotas[event] = min(size, int(exact))
            remainders.append((exact - int(exact), event))
        for _, event in sorted(remainders, key=lambda item: (-item[0], item[1])):
            if sum(quotas.values()) >= top_n:
                break
            if quotas[event] < sizes[event]:
                quotas[event] += 1
        return quotas

    if top_n >= len(sizes):
        for event, size in sizes.items():
            quotas[event] = min(1, size)
    while sum(quotas.values()) < top_n:
        open_events = [event for event in sizes if quotas[event] < sizes[event]]
        if not open_events:
            break
        event = max(
            open_events,
            key=lambda candidate: (
                sizes[candidate] / (2 * quotas[candidate] + 1),
                -candidate,
            ),
        )
        quotas[event] += 1
    return quotas


def _centered_vectors(photos: list[Photo]) -> dict[int, np.ndarray]:
    with_embedding = [photo for photo in photos if photo.embedding]
    if not with_embedding:
        return {}
    matrix = np.asarray([photo.embedding for photo in with_embedding], dtype=np.float32)
    matrix = matrix - matrix.mean(axis=0)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 1e-9)
    return {
        photo.id: vector for photo, vector in zip(with_embedding, matrix) if photo.id is not None
    }


def select_photos(photos: list[Photo], profile: SelectionProfile) -> list[SelectedPhoto]:
    """Select the best photos with event quotas, day/cluster caps and MMR diversity.

    Candidates are the best photo of each similarity group. The greedy loop is fully
    deterministic: value, then score, then capture time and path break ties.
    """
    candidates = best_per_group(photos)
    if not candidates or profile.top_n <= 0:
        return []
    sizes: dict[int, int] = defaultdict(int)
    for photo in candidates:
        sizes[_event_id(photo)] += 1
    quotas = event_quotas(dict(sizes), profile.top_n, profile.event_quota)
    vectors = _centered_vectors(candidates)

    selected: list[SelectedPhoto] = []
    day_counts: dict[str, int] = defaultdict(int)
    cluster_counts: dict[int, int] = defaultdict(int)
    remaining = {photo.id: photo for photo in candidates if photo.id is not None}

    while len(selected) < profile.top_n:
        eligible = []
        for photo in remaining.values():
            if quotas.get(_event_id(photo), 0) <= 0:
                continue
            if profile.max_per_day and day_counts[_day(photo)] >= profile.max_per_day:
                continue
            if (
                profile.max_per_cluster
                and cluster_counts[_cluster_id(photo)] >= profile.max_per_cluster
            ):
                continue
            eligible.append(photo)
        if not eligible:
            break

        def value(photo: Photo) -> float:
            vector = vectors.get(photo.id) if photo.id is not None else None
            if vector is None:
                return photo.score
            similarities = [
                float(vector @ vectors[other.photo.id])
                for other in selected
                if other.photo.id in vectors
            ]
            return photo.score - profile.diversity * max([0.0, *similarities])

        best = min(
            eligible,
            key=lambda photo: (
                -value(photo),
                -photo.score,
                photo.taken or datetime.max,
                photo.path,
            ),
        )
        remaining.pop(best.id)
        quotas[_event_id(best)] -= 1
        day_counts[_day(best)] += 1
        cluster_counts[_cluster_id(best)] += 1
        reason = f"best of group {best.group_id}" if best.group_id is not None else "best photo"
        if selected:
            reason += ", diverse"
        selected.append(
            SelectedPhoto(
                photo=best,
                rank=len(selected) + 1,
                score=best.score,
                reason=reason,
                quota_rule=f"{profile.event_quota}:event={_event_id(best)}",
            )
        )

    for item in selected:
        item.photo.selected = True
        item.photo.reason = item.reason
        item.photo.quota_rule = item.quota_rule
    return selected
