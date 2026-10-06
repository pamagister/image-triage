"""Configurable scoring and star ratings."""

from collections import defaultdict

from image_triage.scan import Photo

# A subject covering this fraction of the image (or more) counts fully.
SUBJECT_FULL_AREA = 0.05


def subject_score(photo: Photo, subject_classes: set[str]) -> float:
    """How prominent the main subject is: confidence x size of the best detection, in [0, 1]."""
    return max(
        (
            d.confidence * min(1.0, d.area / SUBJECT_FULL_AREA)
            for d in photo.objects
            if d.label in subject_classes
        ),
        default=0.0,
    )


def score_photos(
    photos: list[Photo],
    sharpness_weight: float,
    exposure_weight: float,
    sharpness_reference: float,
    object_weight: float = 0.0,
    subject_classes: set[str] = frozenset(),
) -> None:
    """Set `photo.score` in [0, 1] as weighted mix of sharpness, exposure and subject.

    `object_weight` should be 0 if no object detection ran.
    """
    total = sharpness_weight + exposure_weight + object_weight
    for photo in photos:
        sharp = min(1.0, photo.sharpness / sharpness_reference)
        photo.score = (
            sharpness_weight * sharp
            + exposure_weight * photo.exposure
            + object_weight * subject_score(photo, subject_classes)
        ) / total


def rate_photos(
    photos: list[Photo],
    blur_threshold: float,
    max_per_group: int,
    min_score_5: float,
    min_score_4: float,
) -> None:
    """Assign 1-5 stars.

    - blurry (sharpness below `blur_threshold`): 1
    - sharp, but not among the best `max_per_group` of its group: 2
    - best of group: 5 / 4 / 3 depending on score
    """
    groups: dict[int, list[Photo]] = defaultdict(list)
    for photo in photos:
        groups[photo.group].append(photo)

    for members in groups.values():
        sharp = [p for p in members if p.sharpness >= blur_threshold]
        best = sorted(sharp, key=lambda p: (-p.score, p.path))[:max_per_group]
        best_ids = {id(p) for p in best}
        for photo in members:
            photo.best_in_group = id(photo) in best_ids
            if photo.sharpness < blur_threshold:
                photo.rating = 1
            elif not photo.best_in_group:
                photo.rating = 2
            elif photo.score >= min_score_5:
                photo.rating = 5
            elif photo.score >= min_score_4:
                photo.rating = 4
            else:
                photo.rating = 3
