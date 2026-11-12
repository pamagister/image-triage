"""Parse and normalise the library page query parameters.

HTML forms always submit a value for every field, so empty strings are common. Parsing them
as plain strings and dropping empties keeps the library page from returning a raw 422
validation document when the user leaves an optional filter blank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlencode

SORT_KEYS = ("taken", "path", "score", "rating", "sharpness", "bokeh", "aesthetic", "subject")

#: Query parameters that are lists of values rather than single numbers or dates.
MULTI_VALUE_KEYS = (
    "rating",
    "event_id",
    "group_id",
    "label",
    "blur",
    "flags",
    "camera_make",
    "camera_model",
)

#: Numeric filters and whether they are integers or floats.
NUMBER_KEYS = {
    "event_id": int,
    "group_id": int,
    "min_score": float,
    "score_max": float,
    "sharpness_min": float,
    "aesthetic_min": float,
    "subject_min": float,
}

#: Date filters, parsed with :meth:`datetime.date.fromisoformat`.
DATE_KEYS = ("date_from", "date_to")


@dataclass(slots=True)
class PhotoQuery:
    """Validated filters plus the state needed to rebuild links."""

    filters: dict[str, Any] = field(default_factory=dict)
    sort: str = "taken"
    order: str = "asc"
    page: int = 1
    search: str = ""

    @property
    def base_query(self) -> str:
        """Query string of every active filter, used by pagination and sort links."""
        params: list[tuple[str, Any]] = []
        for key, value in self.filters.items():
            if value in (None, "", []):
                continue
            if isinstance(value, (list, tuple)):
                params.extend((key, str(item)) for item in value)
            else:
                params.append((key, value))
        params.append(("sort", self.sort))
        params.append(("order", self.order))
        if self.search:
            params.insert(0, ("q", self.search))
        return urlencode(params)

    @property
    def label(self) -> str:
        """Human-readable summary of the active filters for the result count."""
        parts = []
        for key, value in self.filters.items():
            if value in (None, "", []):
                continue
            if isinstance(value, (list, tuple)):
                parts.append(f"{key}={','.join(str(item) for item in value)}")
            else:
                parts.append(f"{key}={value}")
        return ", ".join(parts)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def parse_photo_query(params: Any) -> PhotoQuery:
    """Build a :class:`PhotoQuery` from request query parameters, tolerating empty values."""
    get = params.getlist if hasattr(params, "getlist") else (lambda key: [params.get(key, "")])
    query = PhotoQuery()

    search = _clean(get("q")[0] if get("q") else "")
    query.search = search

    for key in MULTI_VALUE_KEYS:
        values = []
        for raw in get(key):
            value = _clean(raw)
            if value and value not in values:
                values.append(value)
        if not values:
            continue
        if key in {"rating", "event_id", "group_id"}:
            parsed = []
            for value in values:
                try:
                    parsed.append(int(value))
                except ValueError:
                    continue
            if parsed:
                query.filters[key] = parsed
        else:
            query.filters[key] = values

    for key, caster in NUMBER_KEYS.items():
        raw = _clean(get(key)[0] if get(key) else "")
        if not raw:
            continue
        try:
            query.filters[key] = caster(raw)
        except ValueError:
            continue

    for key in DATE_KEYS:
        raw = _clean(get(key)[0] if get(key) else "")
        if not raw:
            continue
        try:
            query.filters[key] = date.fromisoformat(raw).isoformat()
        except ValueError:
            continue

    sort = _clean(get("sort")[0] if get("sort") else "")
    query.sort = sort if sort in SORT_KEYS else "taken"
    order = _clean(get("order")[0] if get("order") else "").lower()
    query.order = "desc" if order == "desc" else "asc"

    page_raw = _clean(get("page")[0] if get("page") else "")
    try:
        query.page = max(1, int(page_raw)) if page_raw else 1
    except ValueError:
        query.page = 1

    return query
