"""Weighted, versioned quality scoring and star rating."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from image_triage.core.models import SCORING_VERSION, BlurKind, Override, Photo
from image_triage.core.settings import Settings
from image_triage.db.repository import Repository
from image_triage.metrics.subjects import subject_value


@dataclass(slots=True)
class ScoreResult:
    """Score plus the component breakdown for one photo."""

    score: float
    components: dict[str, float]
    weights: dict[str, float]
    contributions: dict[str, float]
    blurry: bool


def _clamp01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def score_photo(photo: Photo, settings: Settings) -> ScoreResult:
    """Compute the weighted score for one photo.

    All components are normalised to 0..1. Sharpness uses the subject/saliency region when
    one was measured so a sharp subject in front of a soft background is not penalised.

    Only an actual motion or defocus blur with sufficient confidence applies the gate: the
    score is halved and the photo is marked blurry. Low global sharpness alone never gates,
    because shallow depth of field is a deliberate aesthetic choice, not a defect.
    """
    scoring = settings.scoring
    raw_components = {
        "sharpness": _clamp01(photo.metrics.sharpness_subject or photo.metrics.sharpness),
        "composition": _clamp01(photo.metrics.composition),
        "aesthetic": _clamp01(photo.metrics.aesthetic),
        "subject": _clamp01(
            subject_value(photo.metrics.subject_score, photo.metrics.subject_rarity)
        ),
    }
    weights = {
        "sharpness": max(0.0, scoring.sharpness_weight),
        "composition": max(0.0, scoring.composition_weight),
        "aesthetic": max(0.0, scoring.aesthetic_weight),
        "subject": max(0.0, scoring.subject_weight),
    }
    weight_sum = sum(weights.values()) or 1.0
    weights = {name: value / weight_sum for name, value in weights.items()}
    contributions = {name: weights[name] * raw_components[name] for name in raw_components}
    score = sum(contributions.values())
    blur_kind = photo.metrics.blur_kind
    blurry = (
        blur_kind in {BlurKind.MOTION, BlurKind.DEFOCUS} and photo.metrics.blur_confidence >= 0.5
    )
    if blurry:
        score *= 0.5
    return ScoreResult(
        score=_clamp01(score),
        components=raw_components,
        weights=weights,
        contributions=contributions,
        blurry=blurry,
    )


def rate_photos(photos: list[Photo], settings: Settings) -> None:
    """Assign 1-5 stars using the best photos per similarity group.

    Photos with a real motion or defocus blur receive 1 star. Sharp non-best photos receive
    2. The best ``max_per_group`` sharp photos receive 5/4/3 according to the score
    thresholds.
    """
    groups: dict[int, list[Photo]] = defaultdict(list)
    for photo in photos:
        groups[photo.group_id or 0].append(photo)

    for members in groups.values():
        scored = [(photo, score_photo(photo, settings)) for photo in members]
        sharp = [(photo, result) for photo, result in scored if not result.blurry]
        sharp.sort(key=lambda item: (-item[1].score, item[0].taken or item[0].path, item[0].path))
        best = sharp[: max(1, settings.selection.max_per_group)]
        best_ids = {id(photo) for photo, _ in best}
        for photo, result in scored:
            photo.score = result.score
            if result.blurry:
                photo.rating = 1
            elif id(photo) not in best_ids:
                photo.rating = 2
            elif result.score >= settings.scoring.min_score_5:
                photo.rating = 5
            elif result.score >= settings.scoring.min_score_4:
                photo.rating = 4
            else:
                photo.rating = 3


def apply_overrides(photos: list[Photo], overrides: list[Override]) -> None:
    """Apply soft CLI/GUI signals without changing originals.

    A rating override replaces the computed rating; keep adds a small score bonus and
    reject applies a penalty. These are intentionally soft so later runs can still
    re-score from the metrics.
    """
    by_id = {override.photo_id: override for override in overrides}
    for photo in photos:
        override = by_id.get(photo.id)
        if override is None:
            continue
        if override.rating is not None:
            photo.rating = override.rating
        if override.keep is True:
            photo.score = min(1.0, photo.score + 0.05)
        elif override.keep is False:
            photo.score = max(0.0, photo.score - 0.10)


def score_library(repository: Repository, settings: Settings) -> list[Photo]:
    """Score and rate all photos, persist the results and return them."""
    photos = repository.all_photos()
    rate_photos(photos, settings)
    apply_overrides(photos, repository.get_overrides())
    repository.update_scores(
        [
            (photo.id, photo.score, photo.rating, photo.flags)
            for photo in photos
            if photo.id is not None
        ]
    )
    return photos


def score_breakdown(photo: Photo, settings: Settings) -> dict[str, Any]:
    """Public breakdown used by the report and JSON CLI."""
    result = score_photo(photo, settings)
    return {
        "score": result.score,
        "formula_version": SCORING_VERSION,
        "weights": result.weights,
        "components": result.components,
        "contributions": result.contributions,
        "blurry": result.blurry,
    }
