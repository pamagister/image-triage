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

SORT_KEYS = (
    "taken",
    "path",
    "score",
    "rating",
    "sharpness",
    "bokeh",
    "aesthetic",
    "subject",
    "blur",
    "group",
    "event",
)
PAGE_SIZES = (10, 20, 50, 100, 200)

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
    "status",
    "root",
    "folder",
)

#: Numeric filters and whether they are integers or floats. Multi-value keys such as
#: ``event_id`` and ``group_id`` stay lists and must not be repeated here: a second
#: parse pass would overwrite the list with a scalar and break ``value in filter`` checks.
NUMBER_KEYS = {
    "min_score": float,
    "score_max": float,
    "sharpness_min": float,
    "sharpness_max": float,
    "bokeh_min": float,
    "bokeh_max": float,
    "blur_min": float,
    "blur_max": float,
    "composition_min": float,
    "composition_max": float,
    "aesthetic_min": float,
    "aesthetic_max": float,
    "subject_min": float,
    "subject_max": float,
    "exposure_min": float,
    "exposure_max": float,
}

#: Integer-valued range filters.
INT_KEYS = {
    "group_size_min": int,
    "group_size_max": int,
}

#: Boolean switches.
BOOL_KEYS = {"hide_rejected"}

#: Date filters, parsed with :meth:`datetime.date.fromisoformat`.
DATE_KEYS = ("date_from", "date_to")


@dataclass(slots=True)
class PhotoQuery:
    """Validated filters plus the state needed to rebuild links."""

    filters: dict[str, Any] = field(default_factory=dict)
    sort: str = "taken"
    order: str = "asc"
    page: int = 1
    page_size: int = 50
    search: str = ""
    view: str = "folders"
    tab: str = "folders"
    selection: str = "any"

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
                params.append((key, "false" if value is False else value))
        if self.selection in {"selected", "unselected"}:
            params.append(("selection", self.selection))
        params.append(("sort", self.sort))
        params.append(("order", self.order))
        params.append(("page_size", self.page_size))
        params.append(("view", self.view))
        params.append(("tab", self.tab))
        if self.search:
            params.insert(0, ("q", self.search))
        return urlencode(params)

    @property
    def label(self) -> str:
        """Human-readable summary of the active filters for the result count."""
        parts = []
        for key, value in self.filters.items():
            if value in (None, "", []) or value is False:
                continue
            if isinstance(value, (list, tuple)):
                parts.append(f"{key}={','.join(str(item) for item in value)}")
            else:
                parts.append(f"{key}={value}")
        return ", ".join(parts)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def parse_photo_query(
    params: Any,
    default_view: str = "folders",
    default_hide_rejected: bool = False,
    default_page_size: int = 50,
) -> PhotoQuery:
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

    for key, caster in INT_KEYS.items():
        raw = _clean(get(key)[0] if get(key) else "")
        if not raw:
            continue
        try:
            query.filters[key] = caster(raw)
        except ValueError:
            continue

    for key in BOOL_KEYS:
        raw = _clean(get(key)[0] if get(key) else "").lower()
        if raw in {"1", "true", "on", "yes"}:
            query.filters[key] = True
        elif raw in {"0", "false", "off", "no"}:
            query.filters[key] = False

    if default_hide_rejected and "hide_rejected" not in query.filters:
        query.filters["hide_rejected"] = True

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

    size_raw = _clean(get("page_size")[0] if get("page_size") else "")
    try:
        page_size = int(size_raw)
        query.page_size = page_size if page_size in PAGE_SIZES else default_page_size
    except ValueError:
        query.page_size = default_page_size

    view = _clean(get("view")[0] if get("view") else "")
    query.view = view if view in {"flat", "folders"} else default_view

    tab = _clean(get("tab")[0] if get("tab") else "")
    query.tab = tab if tab in {"folders", "filters"} else "folders"

    selection = _clean(get("selection")[0] if get("selection") else "")
    query.selection = selection if selection in {"selected", "unselected"} else "any"

    return query
