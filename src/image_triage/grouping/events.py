"""Event detection from capture time, day boundaries and GPS jumps."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from image_triage.core.models import Event, Photo

EARTH_RADIUS_KM = 6371.0


def _haversine_km(first: tuple[float, float] | None, second: tuple[float, float] | None) -> float:
    if first is None or second is None:
        return 0.0
    lat1, lon1 = first
    lat2, lon2 = second
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _event_label(photo: Photo, start: datetime) -> str:
    parent = Path(photo.path).parent
    folder = parent.name if str(parent) not in {".", ""} else ""
    date = start.strftime("%Y-%m-%d")
    return f"{folder} {date}".strip() if folder else date


def detect_events(
    photos: list[Photo], gap_s: float, gps_jump_km: float
) -> tuple[list[Event], list[tuple[int, int]]]:
    """Cluster photos into events.

    A new event starts when the capture-time gap exceeds ``gap_s``, the calendar day
    changes, or two consecutive photos are farther apart than ``gps_jump_km``.

    Returns:
        Events with ids set to their 1-based index and ``(photo_id, event_index)`` pairs.
    """
    if not photos:
        return [], []
    ordered = sorted(
        photos,
        key=lambda photo: (
            photo.taken or datetime.max,
            photo.path,
        ),
    )
    events: list[Event] = []
    assignments: list[tuple[int, int]] = []
    current: list[Photo] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        start = current[0].taken
        end = current[-1].taken
        source = "time"
        if len(events) > 0 and _last_split_source:
            source = _last_split_source
        event = Event(
            id=len(events) + 1,
            start=start,
            end=end,
            label=_event_label(current[0], start) if start else "",
            source=source,
            photo_count=len(current),
        )
        events.append(event)
        for photo in current:
            if photo.id is not None:
                assignments.append((photo.id, event.id))
        current = []

    _last_split_source = "time"
    previous = ordered[0]
    current.append(previous)
    for photo in ordered[1:]:
        previous_time = previous.taken
        current_time = photo.taken
        gap = (
            (current_time - previous_time).total_seconds()
            if previous_time and current_time
            else 0.0
        )
        day_change = bool(
            previous_time and current_time and previous_time.date() != current_time.date()
        )
        jump = _haversine_km(
            (previous.gps_lat, previous.gps_lon) if previous.gps_lat is not None else None,
            (photo.gps_lat, photo.gps_lon) if photo.gps_lat is not None else None,
        )
        gps_split = jump > gps_jump_km
        if gap > gap_s or day_change or gps_split:
            flush()
            _last_split_source = "gps" if gps_split else "time"
            current.append(photo)
        else:
            current.append(photo)
        previous = photo
    flush()
    return events, assignments
