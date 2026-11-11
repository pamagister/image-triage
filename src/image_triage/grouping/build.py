"""Build and persist similarity groups and events for the current library."""

from __future__ import annotations

from image_triage.core.models import Photo
from image_triage.core.settings import Settings
from image_triage.db.repository import Repository
from image_triage.grouping.events import detect_events
from image_triage.grouping.similarity import group_photos


def build_groups_and_events(repository: Repository, settings: Settings) -> list[Photo]:
    """Group similar photos, detect events and persist both assignments."""
    photos = repository.all_photos()
    group_ids = group_photos(photos, settings.similarity)
    assignments = [
        (photo.id, group_id) for photo, group_id in zip(photos, group_ids) if photo.id is not None
    ]
    repository.set_groups(assignments)
    for photo, group_id in zip(photos, group_ids):
        photo.group_id = group_id

    events, event_assignments = detect_events(
        photos,
        settings.similarity.event_gap_s,
        settings.similarity.gps_jump_km,
    )
    stored = repository.set_events(events, [])
    index_to_id = {index: event.id for index, event in enumerate(stored, start=1)}
    remapped = [
        (photo_id, index_to_id[event_id])
        for photo_id, event_id in event_assignments
        if event_id in index_to_id
    ]
    repository.assign_events(remapped)
    event_by_id = {event.id: event for event in stored}
    for photo in photos:
        photo.event_id = next(
            (event_by_id[event_id].id for pid, event_id in remapped if pid == photo.id),
            None,
        )
    return photos
