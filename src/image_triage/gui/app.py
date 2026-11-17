"""Local FastAPI web GUI for browsing, comparing and curating a library."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.datastructures import QueryParams

from image_triage.analysis.analyze import analyze_library
from image_triage.analysis.pipeline import run_pipeline
from image_triage.core.errors import UsageError
from image_triage.core.models import BlurKind, ExportMode, OverrideSource, Photo
from image_triage.core.settings import Settings, load_settings
from image_triage.db.repository import Repository
from image_triage.export.export import export_photos
from image_triage.export.previews import preview_path
from image_triage.grouping.build import build_groups_and_events
from image_triage.gui.library_status import library_status
from image_triage.gui.query import PhotoQuery, parse_photo_query
from image_triage.gui.settings_files import replace_settings_files
from image_triage.io.scan import find_images
from image_triage.scoring.score import score_library
from image_triage.selection.presets import (
    FILTER_FIELD_KINDS,
    FILTER_FIELDS,
    active_presets,
    filters_path,
    load_presets,
    overrides_from_field_values,
    preset_from_mapping,
    presets_yaml,
)
from image_triage.selection.profiles import (
    SelectionProfile,
    load_profile,
    load_profiles,
    profiles_path,
    profiles_yaml,
)
from image_triage.selection.select import best_per_group, select_photos

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
PER_PAGE = 60

#: Human labels for active filter chips.
FILTER_LABELS = {
    "q": "search",
    "rating": "rating",
    "event_id": "event",
    "group_id": "group",
    "group_size_min": "group size min",
    "group_size_max": "group size max",
    "label": "label",
    "blur": "blur",
    "flags": "flags",
    "camera_make": "camera make",
    "camera_model": "camera model",
    "date_from": "from",
    "date_to": "to",
    "min_score": "score min",
    "score_max": "score max",
    "sharpness_min": "sharpness min",
    "sharpness_max": "sharpness max",
    "bokeh_min": "bokeh min",
    "bokeh_max": "bokeh max",
    "blur_min": "blur min",
    "blur_max": "blur max",
    "composition_min": "composition min",
    "composition_max": "composition max",
    "aesthetic_min": "aesthetic min",
    "aesthetic_max": "aesthetic max",
    "subject_min": "subject min",
    "subject_max": "subject max",
    "exposure_min": "exposure min",
    "exposure_max": "exposure max",
    "status": "status",
    "hide_rejected": "hide rejected",
    "root": "root",
    "folder": "folder",
}

#: Default slider values are always submitted by the range controls but are not active filters.
DEFAULT_FILTER_VALUES = {
    "min_score": 0.0,
    "score_max": 1.0,
    "sharpness_min": 0.0,
    "sharpness_max": 1.0,
    "bokeh_min": 0.0,
    "bokeh_max": 1.0,
    "blur_min": 0.0,
    "blur_max": 1.0,
    "composition_min": 0.0,
    "composition_max": 1.0,
    "aesthetic_min": 0.0,
    "aesthetic_max": 1.0,
    "subject_min": 0.0,
    "subject_max": 1.0,
    "exposure_min": 0.0,
    "exposure_max": 1.0,
}

#: Jobs that write to the state database and therefore block a library-root change.
ACTIVE_JOB_STATUSES = ("pending", "running")
MEDIA_CACHE_CONTROL = "public, max-age=604800"


class PhotoIdsRequest(BaseModel):
    """Location ids whose summaries the review panel requests."""

    location_ids: list[int] = []


class StatusRequest(BaseModel):
    """Accepted/rejected/none update for explicit locations or a filtered scope."""

    location_ids: list[int] = []
    filters: dict[str, Any] = {}
    status: str


class SelectBestRequest(BaseModel):
    """Best-N request over a filtered scope."""

    filters: dict[str, Any] = {}
    n: int = 20
    mode: str = "add"
    existing_ids: list[int] = []
    include_rejected: bool | None = None
    profile: str | None = None


class GroupBestRequest(BaseModel):
    """Best-of-group request over a filtered scope."""

    filters: dict[str, Any] = {}
    mode: str = "add"
    existing_ids: list[int] = []
    include_rejected: bool | None = None
    profile: str | None = None


def _current_settings(request: Request) -> Settings:
    """Settings of the running app, including a library root chosen in the GUI."""
    return request.app.state.settings


def _configured_roots(settings: Settings) -> list[Path]:
    """Configured roots without duplicates, or the legacy single root as fallback."""
    roots: list[Path] = []
    seen: set[Path] = set()
    for path in settings.input.roots:
        if not str(path).strip():
            continue
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            roots.append(resolved)
            seen.add(resolved)
    if roots:
        return roots
    return [settings.input.root.expanduser().resolve()]


def _media_path(settings: Settings, photo: Photo) -> Path:
    preview = preview_path(photo, Path(settings.cache_path) / "previews")
    if preview.is_file():
        return preview
    path = photo.absolute_path
    if not path.is_file():
        raise HTTPException(404, "photo not found")
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root) for root in settings.watched_roots):
        raise HTTPException(404, "photo not found")
    return resolved


def _active_jobs(repository: Repository) -> list[dict[str, Any]]:
    return [job for job in repository.list_jobs() if job["status"] in ACTIVE_JOB_STATUSES]


def _active_profile_name(settings: Settings) -> str:
    """Return the configured active profile, falling back to the first available profile."""
    profiles = load_profiles(settings, create=False)
    names = {profile.name for profile in profiles}
    if settings.selection.profile in names:
        return settings.selection.profile
    return profiles[0].name if profiles else settings.selection.profile


def _count_files(root: Path, exclude: tuple[str, ...]) -> int:
    """Number of supported images below ``root`` after configured exclusions."""
    if not root.is_dir():
        return 0
    excluded = tuple(root / name for name in exclude)
    try:
        return len(find_images(root, excluded))
    except OSError:
        return 0


def _root_rows(settings: Settings, repository: Repository) -> list[dict[str, Any]]:
    """Settings-page rows with on-disk and analyzed image counts per configured root."""
    stored = {item["path"]: item for item in repository.roots()}
    active = set(settings.watched_roots)
    rows: list[dict[str, Any]] = []
    for root in _configured_roots(settings):
        rows.append(
            {
                "path": str(root),
                "exists": root.is_dir(),
                "enabled": root in active,
                "disk_images": _count_files(root, tuple(settings.input.exclude)),
                "analyzed": int(stored.get(str(root), {}).get("photos", 0)),
            }
        )
    return rows


def _is_inside(candidate: Path, root: Path) -> bool:
    """True when ``candidate`` is the library root or lives below it."""
    try:
        return candidate.resolve().is_relative_to(root)
    except OSError:
        return False


def _default_output(settings: Settings, now: datetime | None = None) -> Path:
    """Timestamped export directory from the central configuration."""
    return settings.export_destination(now)


def _url_with(query, **overrides: Any) -> str:
    """Build a library URL from the active filters plus explicit overrides."""
    params: list[tuple[str, Any]] = []
    for key, value in query.filters.items():
        if key in overrides or value in (None, "", []):
            continue
        if isinstance(value, (list, tuple)):
            params.extend((key, str(item)) for item in value)
        else:
            params.append((key, "false" if value is False else value))
    params.extend([("sort", query.sort), ("order", query.order)])
    if "view" not in overrides:
        params.append(("view", query.view))
    if "tab" not in overrides and query.tab != "folders":
        params.append(("tab", query.tab))
    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            params.extend((key, str(item)) for item in value)
        elif value is True:
            params.append((key, "true"))
        elif value is False:
            params.append((key, "false"))
        else:
            params.append((key, str(value)))
    if query.search and "q" not in overrides:
        params.insert(0, ("q", query.search))
    return "/?" + urlencode(params)


def _filter_chips(query: PhotoQuery) -> list[dict[str, str]]:
    """Human-readable active filters with a URL that removes each one."""
    chips: list[dict[str, str]] = []
    for key, value in query.filters.items():
        if value in (None, "", []) or value is False:
            continue
        if key in DEFAULT_FILTER_VALUES and value == DEFAULT_FILTER_VALUES[key]:
            continue
        label = FILTER_LABELS.get(key, key)
        if value is True:
            display = "yes"
        elif isinstance(value, (list, tuple)):
            display = ", ".join(str(item) for item in value)
        else:
            display = str(value)
        chips.append(
            {
                "key": key,
                "label": label,
                "value": display,
                "url": _url_with(query, **{key: None}),
            }
        )
    return chips


def _filters_from_mapping(values: dict[str, Any], default_view: str) -> dict[str, Any]:
    """Normalise JSON filter values through the same parser used by library URLs."""
    params: list[tuple[str, str]] = []
    for key, value in values.items():
        if value is None or value is False:
            continue
        if isinstance(value, (list, tuple)):
            params.extend((key, str(item)) for item in value if item is not None)
        else:
            params.append((key, str(value)))
    query = parse_photo_query(QueryParams(params), default_view=default_view)
    filters = dict(query.filters)
    if query.search:
        filters["search"] = query.search
    return filters


def _photo_summary(photo: Photo) -> dict[str, Any]:
    """Lightweight JSON shape used by the selection review panel."""
    location_id = photo.location_id or photo.id
    return {
        "photo_id": photo.id,
        "location_id": location_id,
        "root": photo.root_path,
        "path": photo.path,
        "name": photo.name,
        "score": round(float(photo.score), 3),
        "rating": photo.rating,
        "keep": photo.keep,
        "group_id": photo.group_id,
        "event_id": photo.event_id,
        "taken": photo.taken.isoformat() if photo.taken else None,
        "url": f"/photo/{photo.id}",
        "media": f"/media/location/{location_id}",
    }


#: Above this many matching photos, best-N runs as a background job.
BEST_N_JOB_THRESHOLD = 2000


def _selection_pool(settings: Settings, photos: list[Photo], include_rejected: bool) -> list[Photo]:
    """Apply rejected/accepted preferences and the soft score signal."""
    pool = [photo for photo in photos if include_rejected or photo.keep is not False]
    if not settings.selection.prefer_accepted:
        return pool
    adjusted: list[Photo] = []
    for photo in pool:
        if photo.keep is True:
            bonus = 0.05
        elif photo.keep is False:
            bonus = -0.10
        else:
            bonus = 0.0
        adjusted.append(replace(photo, score=max(0.0, min(1.0, float(photo.score) + bonus))))
    return adjusted


def _best_selection(
    settings: Settings,
    photos: list[Photo],
    n: int,
    *,
    group_best: bool,
    profile_name: str | None = None,
) -> list[Photo]:
    """Choose the best photos or the best photo per similarity group."""
    if group_best:
        return best_per_group(photos)
    profile = load_profile(settings, profile_name, {"top_n": max(0, n)})
    return [item.photo for item in select_photos(photos, profile)]


def _selection_result(
    settings: Settings,
    repository: Repository,
    filters: dict[str, Any],
    *,
    n: int,
    mode: str,
    existing_ids: list[int],
    include_rejected: bool,
    group_best: bool = False,
    profile_name: str | None = None,
) -> dict[str, Any]:
    """Compute a best-N or best-of-group result without touching the client selection."""
    if mode not in {"add", "replace"}:
        raise ValueError("mode must be add or replace")
    photos = repository.list_photos(**filters, sort="score", order="desc")
    pool = _selection_pool(settings, photos, include_rejected)
    existing = [int(value) for value in existing_ids]
    existing_set = set(existing)
    candidates = [
        photo
        for photo in pool
        if photo.location_id is not None and photo.location_id not in existing_set
    ]
    selected = _best_selection(
        settings,
        candidates if mode == "add" else pool,
        n,
        group_best=group_best,
        profile_name=profile_name,
    )
    selected_ids: list[int] = []
    for photo in selected:
        location_id = photo.location_id
        if location_id is not None and location_id not in selected_ids:
            selected_ids.append(int(location_id))
    if mode == "add":
        final_ids = list(dict.fromkeys([*existing, *selected_ids]))
    else:
        final_ids = selected_ids
    return {
        "location_ids": final_ids,
        "selected_ids": selected_ids,
        "added_ids": [value for value in final_ids if value not in existing_set],
        "summary": {
            "candidates": len(photos),
            "eligible": len(pool),
            "groups": len({photo.group_id for photo in pool if photo.group_id is not None}),
            "selected": len(selected_ids),
            "total": len(final_ids),
            "mode": mode,
            "group_best": group_best,
            "include_rejected": include_rejected,
        },
    }


def _folder_tree(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group flat folder rows into a nested navigation tree, one root per library root."""
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for item in items:
        node = {**item, "children": []}
        nodes[(item["root"], item["folder"])] = node
        if item["folder"] == ".":
            roots.append(node)
    for item in items:
        if item["folder"] == ".":
            continue
        node = nodes[(item["root"], item["folder"])]
        parent_folder = item["folder"].rsplit("/", 1)[0] if "/" in item["folder"] else "."
        parent = nodes.get((item["root"], parent_folder))
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots


def _run_job(settings: Settings, job_id: int, kind: str, payload: dict[str, Any]) -> None:
    repository = Repository.open(settings.database_path)
    last_progress = 0.0
    try:
        repository.update_job(job_id, status="running", progress=0.05)
        roots = settings.watched_roots
        output = Path(settings.cache_path) / "gui-runs" / str(job_id)

        def report_progress(event: dict[str, Any]) -> None:
            nonlocal last_progress
            if event.get("event") not in {"photo", "progress"}:
                return
            total = int(event.get("total") or 0)
            done = int(event.get("done") or 0)
            if total <= 0:
                return
            fraction = min(0.99, 0.05 + 0.9 * done / total)
            if fraction >= last_progress + 0.01 or done == total:
                repository.update_job(job_id, status="running", progress=fraction)
                last_progress = fraction

        if kind == "scan":
            analysis = analyze_library(settings, repository, progress=report_progress)
            build_groups_and_events(repository, settings)
            score_library(repository, settings)
            summary = {
                "analysis": analysis.to_dict(),
                "scored": repository.count_content(),
                "removed": analysis.missing,
            }
        elif kind == "analyze":
            result = analyze_library(settings, repository, progress=report_progress)
            summary = result.to_dict()
        elif kind == "select":
            result = run_pipeline(
                settings,
                repository,
                output=output,
                top_n=int(payload.get("top_n", settings.selection.top_n)),
                export=False,
                progress=report_progress,
            )
            summary = result.to_dict()
        elif kind in {"select-best", "select-group-best"}:
            filters = _filters_from_mapping(
                dict(payload.get("filters", {})), settings.gui.default_view
            )
            result = _selection_result(
                settings,
                repository,
                filters,
                n=int(payload.get("n", settings.selection.top_n)),
                mode=str(payload.get("mode", "add")),
                existing_ids=[int(value) for value in payload.get("existing_ids", [])],
                include_rejected=bool(
                    payload.get("include_rejected", settings.selection.include_rejected)
                ),
                group_best=kind == "select-group-best",
                profile_name=payload.get("profile"),
            )
            summary = result
        elif kind == "export":
            mode = ExportMode.COPY
            target = Path(payload["output"]).expanduser() if payload.get("output") else output
            if any(_is_inside(target, root) for root in roots):
                raise ValueError("the export target must be outside every library root")
            scope = payload.get("scope", "filtered")
            if scope == "selected":
                location_ids = [int(value) for value in payload.get("location_ids", [])]
                photos = [
                    photo
                    for photo in (repository.photo_by_location(lid) for lid in location_ids)
                    if photo is not None
                ]
            else:
                photos = repository.list_photos(
                    **{
                        key: value
                        for key, value in payload.get("filters", {}).items()
                        if value not in (None, "", [])
                    }
                )
            if not photos:
                raise ValueError(f"no photos to export for scope '{scope}'")
            layout = str(payload.get("layout", settings.export.layout))
            rerender = bool(payload.get("rerender", settings.export.rerender))
            max_long_edge = payload.get("max_long_edge", settings.export.max_long_edge)
            jpeg_quality = int(payload.get("jpeg_quality", settings.export.jpeg_quality))
            exported = export_photos(
                photos,
                roots[0] if roots else Path("."),
                target,
                mode,
                layout=layout,
                rerender=rerender,
                max_long_edge=None if max_long_edge in (None, "") else int(max_long_edge),
                jpeg_quality=jpeg_quality,
            )
            summary = {
                "exported": len(exported),
                "output": str(target),
                "mode": mode.value,
                "layout": layout,
                "rerendered": rerender,
                "scope": scope,
            }
        else:
            raise ValueError(f"unknown job kind: {kind}")
        repository.update_job(job_id, status="completed", progress=1.0, result=summary)
    except Exception as exc:  # background worker must never crash the server
        repository.update_job(job_id, status="failed", result={"error": str(exc)})
    finally:
        repository.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application around a settings object."""
    app = FastAPI(title="Image Triage", version="1.0")
    app.state.settings = settings or load_settings()
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def repository(request: Request) -> Repository:
        """One connection per request; never shared with another request or job thread."""
        repo = Repository.open(_current_settings(request).database_path)
        try:
            yield repo
        finally:
            repo.close()

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        settings = _current_settings(request)
        roots = [str(path) for path in settings.watched_roots]
        return {"ok": True, "roots": roots, "input": roots[0] if roots else ""}

    @app.get("/setup", response_model=None)
    def setup_redirect() -> RedirectResponse:
        """Keep old bookmarks working without exposing the removed setup form."""
        return RedirectResponse("/settings", status_code=308)

    @app.get("/api/browse")
    def browse(path: str = "~") -> dict[str, Any]:
        """List directories below ``path`` for the settings directory picker."""
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        else:
            target = target.resolve()
        if not target.is_dir():
            raise HTTPException(400, "not a directory")
        try:
            directories = sorted(
                (item for item in target.iterdir() if item.is_dir()),
                key=lambda item: item.name.lower(),
            )
        except OSError as exc:
            raise HTTPException(400, f"cannot read directory: {exc}") from exc
        return {
            "path": str(target),
            "parent": None if target.parent == target else str(target.parent),
            "directories": [{"name": item.name, "path": str(item)} for item in directories],
        }

    def _library_response(
        request: Request,
        repo: Repository,
        *,
        error: str = "",
        status_code: int = 200,
    ) -> HTMLResponse:
        """Render the library page with the current filters and an optional message."""
        settings = _current_settings(request)
        query = parse_photo_query(
            request.query_params,
            default_view=settings.gui.default_view,
            default_hide_rejected=settings.gui.filters.hide_rejected,
        )
        filters = dict(query.filters)
        if query.search:
            filters["search"] = query.search
        total = repo.count_photos(**filters)
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(max(1, query.page), pages)
        # The tree is navigation: ignore folder and root selection so every node stays visible.
        tree_filters = {
            key: value for key, value in filters.items() if key not in {"folder", "root"}
        }
        folders = repo.folder_counts(**tree_filters)
        for item in folders:
            folder = None if item["folder"] == "." else item["folder"]
            item["url"] = _url_with(
                query,
                view="folders",
                root=item["root"],
                folder=folder,
                page=1,
                tab="folders",
            )
            item["depth"] = 0 if item["folder"] == "." else item["folder"].count("/") + 1
        tree = _folder_tree(folders)
        storage_errors = []
        try:
            profiles = load_profiles(settings, create=False)
        except (OSError, UsageError) as exc:
            profiles = []
            storage_errors.append(str(exc))
        try:
            all_presets = load_presets(settings, create=False)
            presets = active_presets(settings)
        except (OSError, UsageError) as exc:
            all_presets = []
            presets = []
            storage_errors.append(str(exc))
        active_profile = _active_profile_name(settings) if profiles else ""
        best_n = next(
            (profile.top_n for profile in profiles if profile.name == active_profile),
            profiles[0].top_n if profiles else settings.selection.top_n,
        )
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "photos": repo.list_photos(
                    **filters,
                    sort=query.sort,
                    order=query.order,
                    limit=PER_PAGE,
                    offset=(page - 1) * PER_PAGE,
                ),
                "events": repo.events(),
                "groups": repo.group_options(),
                "labels": repo.label_options(),
                "blur_kinds": [kind.value for kind in BlurKind],
                "total": total,
                "page": page,
                "pages": pages,
                "sort": query.sort,
                "order": query.order,
                "latest_run": repo.latest_run(),
                "filters": filters,
                "search": query.search,
                "base_query": query.base_query,
                "view": query.view,
                "tab": query.tab,
                "chips": _filter_chips(query),
                "presets": [
                    {
                        "name": preset.name,
                        "label": preset.label,
                        "url": _url_with(query, **preset.overrides),
                    }
                    for preset in presets
                ],
                "all_presets": all_presets,
                "filter_settings": settings.gui.filters,
                "selection_profiles": profiles,
                "active_profile": active_profile,
                "best_n": best_n,
                "view_flat": _url_with(query, view="flat", folder=None, page=1),
                "view_folders": _url_with(query, view="folders", page=1),
                "folders": tree,
                "selected_folders": set(filters.get("folder", [])),
                "tile_fields": _current_settings(request).gui.tile_fields,
                "active_jobs": _active_jobs(repo),
                "status": library_status(_current_settings(request), repo),
                "filter_options": repo.filter_options(),
                "error": " ".join([error, *storage_errors]).strip(),
                "default_output": str(_default_output(_current_settings(request))),
                "roots": repo.roots(),
            },
            status_code=status_code,
        )

    def _export_error(request: Request, repo: Repository, message: str) -> HTMLResponse:
        """Render the library page with an export error."""
        return _library_response(request, repo, error=message, status_code=400)

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def index(
        request: Request,
        repo: Repository = Depends(repository),
    ) -> HTMLResponse | RedirectResponse:
        status = library_status(_current_settings(request), repo)
        # An empty library would otherwise render as a blank page; scan it once automatically.
        if status.empty and not _active_jobs(repo):
            job_id = repo.create_job("scan", {})
            threading.Thread(
                target=_run_job,
                args=(_current_settings(request), job_id, "scan", {}),
                daemon=True,
            ).start()
            return RedirectResponse("/jobs", status_code=303)
        return _library_response(request, repo)

    @app.post("/presets/save", response_model=None)
    def save_current_preset(
        request: Request,
        repo: Repository = Depends(repository),
        preset_target: str = Form(""),
        preset_name: str = Form(""),
        preset_label: str = Form(""),
    ) -> HTMLResponse | RedirectResponse:
        """Save the current library filters as a new or existing preset."""
        settings = _current_settings(request)
        if _active_jobs(repo):
            return _library_response(
                request, repo, error="cannot save a preset while a job is active", status_code=409
            )
        query = parse_photo_query(
            request.query_params,
            default_view=settings.gui.default_view,
            default_hide_rejected=settings.gui.filters.hide_rejected,
        )
        try:
            presets = load_presets(settings, create=False)
            existing = next((item for item in presets if item.name == preset_target), None)
            if preset_target and existing is None:
                raise ValueError("preset to update was not found")
            name = existing.name if existing else preset_name.strip()
            if not name:
                raise ValueError("enter a name for the new preset")
            if not existing and any(item.name == name for item in presets):
                raise ValueError("a preset with that name already exists; choose it to update")
            overrides = dict(query.filters)
            if query.search:
                overrides["q"] = query.search
            preset = preset_from_mapping(
                {
                    "name": name,
                    "label": preset_label.strip() or (existing.label if existing else name),
                    "overrides": overrides,
                },
                path=filters_path(settings),
            )
            if existing:
                presets[presets.index(existing)] = preset
            else:
                presets.append(preset)
            updated = settings.model_copy(deep=True)
            if not existing and name not in updated.gui.filters.presets:
                updated.gui.filters.presets.append(name)
            files = {
                filters_path(updated): presets_yaml(presets),
                updated.config_path: yaml.safe_dump(
                    updated.model_dump(mode="json"), sort_keys=False
                ),
            }
            with replace_settings_files(files):
                pass
        except (OSError, UsageError, ValueError, RuntimeError) as exc:
            return _library_response(request, repo, error=str(exc), status_code=400)
        request.app.state.settings = updated
        return RedirectResponse(_url_with(query, tab="filters"), status_code=303)

    @app.post("/export", response_model=None)
    def start_export(
        request: Request,
        repo: Repository = Depends(repository),
        scope: str = Form("selected"),
        output: str = Form(""),
        photo_ids: str = Form(""),
        layout: str = Form(""),
        rerender: bool = Form(False),
        max_long_edge: str = Form(""),
        jpeg_quality: str = Form(""),
    ) -> HTMLResponse | RedirectResponse:
        """Export either the checked photos or the current filtered view as a background job."""
        settings = _current_settings(request)
        roots = settings.watched_roots
        query = parse_photo_query(
            request.query_params,
            default_view=settings.gui.default_view,
            default_hide_rejected=settings.gui.filters.hide_rejected,
        )
        filters = dict(query.filters)
        if query.search:
            filters["search"] = query.search

        target = Path(output).expanduser() if output.strip() else _default_output(settings)
        if any(_is_inside(target, root) for root in roots):
            return _export_error(
                request, repo, "the export target must be outside every library root"
            )

        if scope == "selected":
            ids = [int(value) for value in photo_ids.split(",") if value.strip().isdigit()]
            if not ids:
                return _export_error(request, repo, "no photos are selected")
            export_payload: dict[str, Any] = {"location_ids": ids}
        else:
            scope_filters = dict(filters)
            if scope == "accepted":
                scope_filters["status"] = ["accepted"]
            if repo.count_photos(**scope_filters) == 0:
                noun = "accepted" if scope == "accepted" else "filtered"
                return _export_error(request, repo, f"no {noun} photos to export")
            export_payload = {"filters": scope_filters}

        payload: dict[str, Any] = {
            "output": str(target),
            "scope": scope,
            "layout": layout or settings.export.layout,
            "rerender": rerender or settings.export.rerender,
            "max_long_edge": max_long_edge or settings.export.max_long_edge,
            "jpeg_quality": int(jpeg_quality)
            if str(jpeg_quality).strip()
            else settings.export.jpeg_quality,
            **export_payload,
        }
        job_id = repo.create_job("export", payload)
        thread = threading.Thread(
            target=_run_job,
            args=(settings, job_id, "export", payload),
            daemon=True,
        )
        thread.start()
        return RedirectResponse("/jobs", status_code=303)

    @app.get("/api/photo-ids")
    def photo_ids(request: Request, repo: Repository = Depends(repository)) -> dict[str, Any]:
        """All photo ids matching the current filters, across every page."""
        settings = _current_settings(request)
        query = parse_photo_query(
            request.query_params,
            default_view=settings.gui.default_view,
            default_hide_rejected=settings.gui.filters.hide_rejected,
        )
        filters = dict(query.filters)
        if query.search:
            filters["search"] = query.search
        ids = repo.photo_ids(**filters)
        return {"ids": ids, "total": len(ids)}

    @app.post("/api/photos")
    def photo_summaries(
        payload: PhotoIdsRequest, repo: Repository = Depends(repository)
    ) -> dict[str, Any]:
        """Return review thumbnails for location ids and report stale ids."""
        photos = repo.photos_by_locations(payload.location_ids)
        found = {photo.location_id for photo in photos if photo.location_id is not None}
        missing = sorted({int(value) for value in payload.location_ids} - found)
        return {
            "photos": [_photo_summary(photo) for photo in photos],
            "missing": missing,
        }

    @app.post("/api/status")
    def set_status(
        payload: StatusRequest,
        request: Request,
        repo: Repository = Depends(repository),
    ) -> dict[str, Any]:
        """Accept, reject or clear the decision for explicit locations or a filtered scope."""
        settings = _current_settings(request)
        if payload.status not in {"accepted", "rejected", "none"}:
            raise HTTPException(400, "status must be accepted, rejected or none")
        if payload.location_ids:
            location_ids = [int(value) for value in payload.location_ids]
            photo_ids = repo.photo_ids_for_locations(location_ids)
        else:
            filters = _filters_from_mapping(payload.filters, settings.gui.default_view)
            location_ids = repo.photo_ids(**filters)
            photo_ids = repo.photo_ids_for_locations(location_ids)
        changed = repo.set_status(photo_ids, payload.status)
        return {
            "status": payload.status,
            "photos": changed,
            "locations": len(location_ids),
            "photo_ids": photo_ids,
        }

    @app.post("/api/select-best")
    def select_best(
        payload: SelectBestRequest,
        request: Request,
        repo: Repository = Depends(repository),
    ) -> dict[str, Any]:
        """Select N photos from the current filtered scope for the browser-local selection."""
        settings = _current_settings(request)
        filters = _filters_from_mapping(payload.filters, settings.gui.default_view)
        include_rejected = (
            settings.selection.include_rejected
            if payload.include_rejected is None
            else payload.include_rejected
        )
        n = max(0, min(int(payload.n), 5000))
        payload_data = {
            "filters": payload.filters,
            "n": n,
            "mode": payload.mode,
            "existing_ids": payload.existing_ids,
            "include_rejected": include_rejected,
            "profile": payload.profile,
        }
        if repo.count_photos(**filters) > BEST_N_JOB_THRESHOLD:
            job_id = repo.create_job("select-best", payload_data)
            thread = threading.Thread(
                target=_run_job,
                args=(settings, job_id, "select-best", payload_data),
                daemon=True,
            )
            thread.start()
            return {"job_id": job_id, "async": True, "summary": {"threshold": BEST_N_JOB_THRESHOLD}}
        try:
            result = _selection_result(
                settings,
                repo,
                filters,
                n=n,
                mode=payload.mode,
                existing_ids=payload.existing_ids,
                include_rejected=include_rejected,
                profile_name=payload.profile,
            )
        except (UsageError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**result, "async": False, "job_id": None}

    @app.post("/api/select-group-best")
    def select_group_best(
        payload: GroupBestRequest,
        request: Request,
        repo: Repository = Depends(repository),
    ) -> dict[str, Any]:
        """Select the best photo of each similarity group in the current filtered scope."""
        settings = _current_settings(request)
        filters = _filters_from_mapping(payload.filters, settings.gui.default_view)
        include_rejected = (
            settings.selection.include_rejected
            if payload.include_rejected is None
            else payload.include_rejected
        )
        payload_data = {
            "filters": payload.filters,
            "mode": payload.mode,
            "existing_ids": payload.existing_ids,
            "include_rejected": include_rejected,
            "profile": payload.profile,
        }
        if repo.count_photos(**filters) > BEST_N_JOB_THRESHOLD:
            job_id = repo.create_job("select-group-best", payload_data)
            thread = threading.Thread(
                target=_run_job,
                args=(settings, job_id, "select-group-best", payload_data),
                daemon=True,
            )
            thread.start()
            return {"job_id": job_id, "async": True, "summary": {"threshold": BEST_N_JOB_THRESHOLD}}
        try:
            result = _selection_result(
                settings,
                repo,
                filters,
                n=0,
                mode=payload.mode,
                existing_ids=payload.existing_ids,
                include_rejected=include_rejected,
                group_best=True,
                profile_name=payload.profile,
            )
        except (UsageError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**result, "async": False, "job_id": None}

    @app.get("/compare/group/{group_id}", response_class=HTMLResponse)
    def compare_group(
        request: Request, group_id: int, repo: Repository = Depends(repository)
    ) -> HTMLResponse:
        """Compare every available photo in one similarity group."""
        photos = repo.list_photos(group_id=group_id, sort="score", order="desc")
        if not photos:
            raise HTTPException(404, "group not found")
        return TEMPLATES.TemplateResponse(
            request,
            "compare.html",
            {"photos": photos, "group_id": group_id, "title": f"Group {group_id}"},
        )

    @app.get("/photo/{photo_id}", response_class=HTMLResponse)
    def photo_detail(
        request: Request, photo_id: int, repo: Repository = Depends(repository)
    ) -> HTMLResponse:
        photo = repo.photo_by_id(photo_id)
        if photo is None:
            raise HTTPException(404, "photo not found")
        similar = (
            repo.list_photos(group_id=photo.group_id, limit=12)
            if photo.group_id is not None
            else []
        )
        return TEMPLATES.TemplateResponse(
            request,
            "photo.html",
            {
                "photo": photo,
                "similar": similar,
                "override": next(
                    (item for item in repo.get_overrides() if item.photo_id == photo_id),
                    None,
                ),
            },
        )

    @app.get("/compare", response_class=HTMLResponse)
    def compare(request: Request, ids: str, repo: Repository = Depends(repository)) -> HTMLResponse:
        photos = []
        for raw in ids.split(","):
            try:
                photo = repo.photo_by_id(int(raw))
            except ValueError:
                photo = None
            if photo is not None:
                photos.append(photo)
        if not photos:
            raise HTTPException(404, "no photos to compare")
        return TEMPLATES.TemplateResponse(request, "compare.html", {"photos": photos})

    def _settings_context(
        request: Request,
        repo: Repository,
        *,
        settings: Settings,
        active_jobs: list[dict[str, Any]] | None = None,
        error: str = "",
        status_code: int = 200,
        saved: bool = False,
    ) -> HTMLResponse:
        """Render the settings page with current root statistics and messages."""
        storage_errors = []
        try:
            profile_rows = load_profiles(settings, create=False)
        except (OSError, UsageError) as exc:
            profile_rows = []
            storage_errors.append(str(exc))
        try:
            preset_rows = load_presets(settings, create=False)
        except (OSError, UsageError) as exc:
            preset_rows = []
            storage_errors.append(str(exc))
        return TEMPLATES.TemplateResponse(
            request,
            "settings.html",
            {
                "settings": settings,
                "root_rows": _root_rows(settings, repo),
                "tile_field_options": [
                    ("score", "score"),
                    ("rating", "rating"),
                    ("taken", "date"),
                    ("sharpness", "sharpness"),
                    ("bokeh", "bokeh"),
                    ("blur", "blur"),
                    ("aesthetic", "aesthetic"),
                    ("subject", "subject"),
                    ("camera", "camera"),
                    ("dimensions", "dimensions"),
                    ("group", "group"),
                    ("event", "event"),
                ],
                "filter_group_options": [
                    ("rating", "Rating"),
                    ("quality", "Quality"),
                    ("sharpness", "Sharpness and blur"),
                    ("date", "Captured date"),
                    ("similar", "Similar shots"),
                ],
                "selection_profile_rows": profile_rows,
                "filter_preset_rows": preset_rows,
                "selection_store_path": profiles_path(settings),
                "filter_store_path": filters_path(settings),
                "preset_fields": [
                    {"key": key, "kind": FILTER_FIELD_KINDS[key]} for key in FILTER_FIELDS
                ],
                "blur_kinds": [kind.value for kind in BlurKind],
                "active_profile": _active_profile_name(settings) if profile_rows else "",
                "active_jobs": _active_jobs(repo) if active_jobs is None else active_jobs,
                "database_override": settings.input.db_path is not None,
                "error": error,
                "storage_errors": storage_errors,
                "saved": saved,
            },
            status_code=status_code,
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_form(request: Request, repo: Repository = Depends(repository)) -> HTMLResponse:
        return _settings_context(
            request,
            repo,
            settings=_current_settings(request),
            error=request.query_params.get("error") or "",
            saved=request.query_params.get("saved") == "1",
        )

    @app.post("/settings", response_model=None)
    def save_settings(
        request: Request,
        repo: Repository = Depends(repository),
        root_paths: list[str] = Form([]),  # noqa: B008
        enabled_roots: list[str] = Form([]),  # noqa: B008
        new_root: str = Form(""),
        add_root: str = Form(""),
        remove_root: str = Form(""),
        exclude: str = Form(""),
        default_view: str = Form("folders"),
        tile_fields: list[str] = Form([]),  # noqa: B008
        filter_groups: list[str] = Form([]),  # noqa: B008
        filter_groups_submitted: bool = Form(False),
        filter_hide_rejected: bool = Form(False),
        filter_hide_rejected_submitted: bool = Form(False),
        selection_include_rejected: bool = Form(False),
        selection_prefer_accepted: bool = Form(True),
        selection_profiles_dir: str = Form(""),
        profile_order: list[str] = Form([]),  # noqa: B008
        profile_name: list[str] = Form([]),  # noqa: B008
        profile_submitted: bool = Form(False),
        add_profile: str = Form(""),
        profile_top_n: list[str] = Form([]),  # noqa: B008
        profile_diversity: list[str] = Form([]),  # noqa: B008
        profile_max_per_group: list[str] = Form([]),  # noqa: B008
        profile_max_per_day: list[str] = Form([]),  # noqa: B008
        profile_max_per_cluster: list[str] = Form([]),  # noqa: B008
        profile_event_quota: list[str] = Form([]),  # noqa: B008
        preset_order: list[str] = Form([]),  # noqa: B008
        preset_name: list[str] = Form([]),  # noqa: B008
        add_preset: str = Form(""),
        preset_label: list[str] = Form([]),  # noqa: B008
        preset_enabled: list[str] = Form([]),  # noqa: B008
        preset_values: list[str] = Form([]),  # noqa: B008
        preset_submitted: bool = Form(False),
        export_layout: str = Form("flat"),
        rerender: bool = Form(False),
        max_long_edge: str = Form(""),
        jpeg_quality: int = Form(85),
        export_destination: str = Form(""),
        blur_sharp_reference: float = Form(120.0),
        blur_blur_reference: float = Form(5.0),
        min_score_5: float = Form(0.75),
        min_score_4: float = Form(0.45),
        yolo_enabled: bool = Form(True),
        aesthetic_enabled: bool = Form(True),
        save_embeddings: bool = Form(True),
        preview_size: int = Form(1024),
    ) -> RedirectResponse | HTMLResponse:
        """Persist runtime settings to the central YAML configuration."""
        settings = _current_settings(request)
        try:
            load_profiles(settings, create=False)
            load_presets(settings, create=False)
        except (OSError, UsageError) as exc:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error=f"cannot save while settings files are invalid: {exc}",
                status_code=400,
            )
        active = _active_jobs(repo)
        if active:
            return _settings_context(
                request,
                repo,
                settings=settings,
                active_jobs=active,
                error="cannot change settings while a job is active",
                status_code=409,
            )

        configured: list[Path] = []
        for raw in root_paths:
            candidate = Path(raw.strip()).expanduser().resolve()
            if candidate not in configured:
                configured.append(candidate)

        enabled: list[Path] = []
        for raw in enabled_roots:
            candidate = Path(raw.strip()).expanduser().resolve()
            if candidate in configured and candidate not in enabled:
                enabled.append(candidate)

        if add_root:
            value = new_root.strip()
            if not value:
                return _settings_context(
                    request,
                    repo,
                    settings=settings,
                    error="enter a folder to add",
                    status_code=400,
                )
            candidate = Path(value).expanduser().resolve()
            if not candidate.is_dir():
                return _settings_context(
                    request,
                    repo,
                    settings=settings,
                    error=f"not a directory: {candidate}",
                    status_code=400,
                )
            if candidate not in configured:
                configured.append(candidate)
            if candidate not in enabled:
                enabled.append(candidate)

        if remove_root:
            removed = Path(remove_root.strip()).expanduser().resolve()
            configured = [path for path in configured if path != removed]
            enabled = [path for path in enabled if path != removed]

        if not configured:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error="at least one watched root is required",
                status_code=400,
            )
        if not enabled:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error="at least one watched root must be active",
                status_code=400,
            )
        missing = [path for path in enabled if not path.is_dir()]
        if missing:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error=f"active root is not a directory: {missing[0]}",
                status_code=400,
            )

        if add_profile:
            existing = set(profile_name)
            suffix = 1
            candidate = "new-profile"
            while candidate in existing:
                suffix += 1
                candidate = f"new-profile-{suffix}"
            profile_name = [*profile_name, candidate]
            profile_top_n = [*profile_top_n, "50"]
            profile_diversity = [*profile_diversity, "0.5"]
            profile_max_per_group = [*profile_max_per_group, "1"]
            profile_max_per_day = [*profile_max_per_day, "5"]
            profile_max_per_cluster = [*profile_max_per_cluster, "3"]
            profile_event_quota = [*profile_event_quota, "sainte_lague"]
            profile_order = [*profile_order, candidate]
        if add_preset:
            existing = set(preset_name)
            suffix = 1
            candidate = "new-preset"
            while candidate in existing:
                suffix += 1
                candidate = f"new-preset-{suffix}"
            preset_name = [*preset_name, candidate]
            preset_label = [*preset_label, "New preset"]
            preset_values = [*preset_values, *([""] * len(FILTER_FIELDS))]
            preset_order = [*preset_order, candidate]

        if profile_submitted and not profile_name:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error="at least one selection profile is required",
                status_code=400,
            )
        if preset_submitted and not preset_name:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error="at least one filter preset is required",
                status_code=400,
            )

        data = settings.model_dump(mode="json")
        data["input"]["roots"] = [str(path) for path in configured]
        data["input"]["disabled_roots"] = [str(path) for path in configured if path not in enabled]
        data["input"]["exclude"] = [item.strip() for item in exclude.split(",") if item.strip()]
        data["gui"]["default_view"] = default_view
        data["gui"]["tile_fields"] = tile_fields or []
        if filter_groups_submitted:
            data["gui"]["filters"]["visible"] = filter_groups
        if filter_hide_rejected_submitted:
            data["gui"]["filters"]["hide_rejected"] = filter_hide_rejected
        data["export"].update(
            {
                "layout": export_layout,
                "rerender": rerender,
                "max_long_edge": int(max_long_edge) if max_long_edge.strip() else None,
                "jpeg_quality": jpeg_quality,
            }
        )
        data["selection"].update(
            {
                "include_rejected": selection_include_rejected,
                "prefer_accepted": selection_prefer_accepted,
                "profiles_dir": selection_profiles_dir or str(settings.selection.profiles_dir),
            }
        )
        data["export"]["destination"] = export_destination.strip() or None
        data["blur"].update(
            {
                "sharp_reference": blur_sharp_reference,
                "blur_reference": blur_blur_reference,
            }
        )
        data["scoring"].update({"min_score_5": min_score_5, "min_score_4": min_score_4})
        data["analysis"].update(
            {
                "yolo_enabled": yolo_enabled,
                "aesthetic_enabled": aesthetic_enabled,
                "save_embeddings": save_embeddings,
                "preview_size": preview_size,
            }
        )
        try:
            updated = type(settings).model_validate(data)
        except Exception as exc:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error=str(exc),
                status_code=400,
            )

        def _preset_overrides_from_form(index: int) -> dict[str, Any]:
            """Build one preset override mapping from the GUI fields."""
            width = len(FILTER_FIELDS)
            start = index * width
            values = preset_values[start : start + width]
            if len(values) != width:
                raise ValueError("filter preset fields are incomplete")
            # Native number/date inputs contain only their value. Keep accepting the
            # previous key=value representation for existing non-browser clients.
            encoded = [
                value if value.startswith(f"{key}=") else f"{key}={value}"
                for key, value in zip(FILTER_FIELDS, values)
            ]
            return overrides_from_field_values(encoded, path=filters_path(updated))

        serialized_files: dict[Path, str] = {}
        try:
            if profile_name:
                profile_fields = [
                    profile_top_n,
                    profile_diversity,
                    profile_max_per_group,
                    profile_max_per_day,
                    profile_max_per_cluster,
                    profile_event_quota,
                ]
                if any(len(field) != len(profile_name) for field in profile_fields):
                    raise ValueError("selection profile fields are incomplete")
                profiles = []
                for index, name in enumerate(profile_name):
                    profiles.append(
                        SelectionProfile(
                            name=name.strip(),
                            top_n=int(profile_top_n[index]),
                            diversity=float(profile_diversity[index]),
                            max_per_group=int(profile_max_per_group[index]),
                            max_per_day=int(profile_max_per_day[index]),
                            max_per_cluster=int(profile_max_per_cluster[index]),
                            event_quota=profile_event_quota[index],
                        )
                    )
                if profile_order:
                    order = {name: index for index, name in enumerate(profile_order)}
                    profiles = [
                        profile
                        for _, profile in sorted(
                            enumerate(profiles),
                            key=lambda pair: (
                                order.get(profile_order[pair[0]], pair[0])
                                if pair[0] < len(profile_order)
                                else pair[0]
                            ),
                        )
                    ]
                serialized_files[profiles_path(updated)] = profiles_yaml(profiles)
                updated.selection.profile = profiles[0].name
            if preset_name:
                if len(preset_name) != len(preset_label):
                    raise ValueError("filter preset fields are incomplete")
                if len(preset_values) != len(preset_name) * len(FILTER_FIELDS):
                    raise ValueError("filter preset fields are incomplete")
                old_to_new = {
                    (
                        preset_order[index]
                        if index < len(preset_order)
                        else preset_name[index].strip()
                    ): preset_name[index].strip()
                    for index in range(len(preset_name))
                }
                presets = []
                for index, name in enumerate(preset_name):
                    raw_values = {
                        "name": name.strip(),
                        "label": preset_label[index].strip() or name.strip(),
                        "overrides": _preset_overrides_from_form(index),
                    }
                    presets.append(preset_from_mapping(raw_values, path=filters_path(updated)))
                if preset_order:
                    order = {name: index for index, name in enumerate(preset_order)}
                    presets = [
                        preset
                        for _, preset in sorted(
                            enumerate(presets),
                            key=lambda pair: (
                                order.get(preset_order[pair[0]], pair[0])
                                if pair[0] < len(preset_order)
                                else pair[0]
                            ),
                        )
                    ]
                serialized_files[filters_path(updated)] = presets_yaml(presets)
                if preset_submitted:
                    updated.gui.filters.presets = [
                        old_to_new.get(name, name)
                        for name in preset_enabled
                        if name in old_to_new or name in {preset.name for preset in presets}
                    ]
        except Exception as exc:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error=str(exc),
                status_code=400,
            )

        serialized_files[updated.config_path] = yaml.safe_dump(
            updated.model_dump(mode="json"), sort_keys=False
        )
        try:
            with replace_settings_files(serialized_files):
                repo.sync_roots(configured, enabled=enabled)
        except Exception as exc:
            return _settings_context(
                request,
                repo,
                settings=settings,
                error=f"could not save settings: {exc}",
                status_code=400,
            )
        request.app.state.settings = updated
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/events", response_class=HTMLResponse)
    def events(request: Request, repo: Repository = Depends(repository)) -> HTMLResponse:
        covers = repo.event_covers()
        timeline = [
            {
                **event.to_dict(),
                "cover": covers.get(event.id),
                "url": f"/?event_id={event.id}&view=folders",
            }
            for event in repo.events()
        ]
        points = repo.gps_points()
        if points:
            min_lat = min(point["lat"] for point in points)
            max_lat = max(point["lat"] for point in points)
            min_lon = min(point["lon"] for point in points)
            max_lon = max(point["lon"] for point in points)
            lat_span = max_lat - min_lat
            lon_span = max_lon - min_lon
            for point in points:
                point["x"] = (point["lon"] - min_lon) / lon_span * 100 if lon_span else 50.0
                point["y"] = (max_lat - point["lat"]) / lat_span * 100 if lat_span else 50.0
        return TEMPLATES.TemplateResponse(
            request,
            "events.html",
            {"timeline": timeline, "points": points},
        )

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request, repo: Repository = Depends(repository)) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "jobs.html", {"jobs": repo.list_jobs()})

    @app.get("/api/jobs/active")
    def active_jobs(repo: Repository = Depends(repository)) -> dict[str, Any]:
        """Active job count for the header status indicator."""
        jobs = _active_jobs(repo)
        return {"count": len(jobs), "kinds": sorted({job["kind"] for job in jobs})}

    @app.post("/scan", response_model=None)
    def start_scan(
        request: Request, repo: Repository = Depends(repository)
    ) -> HTMLResponse | RedirectResponse:
        """Start the unified scan job, or report the job that is already running."""
        active = _active_jobs(repo)
        if active:
            return RedirectResponse("/jobs", status_code=303)
        job_id = repo.create_job("scan", {})
        thread = threading.Thread(
            target=_run_job,
            args=(_current_settings(request), job_id, "scan", {}),
            daemon=True,
        )
        thread.start()
        return RedirectResponse("/jobs", status_code=303)

    @app.get("/jobs/{job_id}")
    def job_status(job_id: int, repo: Repository = Depends(repository)) -> dict[str, Any]:
        job = repo.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job

    @app.post("/photo/{photo_id}/override")
    def override(
        photo_id: int,
        repo: Repository = Depends(repository),
        rating: int | None = Form(None),
        keep: str | None = Form(None),
    ) -> RedirectResponse:
        keep_value = None if keep in {None, ""} else keep == "keep"
        repo.set_override(photo_id, rating=rating, keep=keep_value, source=OverrideSource.GUI)
        return RedirectResponse(f"/photo/{photo_id}", status_code=303)

    @app.get("/media/location/{location_id}")
    def location_media(
        request: Request, location_id: int, repo: Repository = Depends(repository)
    ) -> FileResponse:
        photo = repo.photo_by_location(location_id)
        if photo is None:
            raise HTTPException(404, "photo not found")
        path = _media_path(_current_settings(request), photo)
        if not path.is_file():
            raise HTTPException(404, "photo file not found")
        return FileResponse(path, headers={"Cache-Control": MEDIA_CACHE_CONTROL})

    @app.get("/media/{photo_id}")
    def media(
        request: Request, photo_id: int, repo: Repository = Depends(repository)
    ) -> FileResponse:
        photo = repo.photo_by_id(photo_id)
        if photo is None:
            raise HTTPException(404, "photo not found")
        path = _media_path(_current_settings(request), photo)
        if not path.is_file():
            raise HTTPException(404, "photo file not found")
        return FileResponse(path, headers={"Cache-Control": MEDIA_CACHE_CONTROL})

    return app


def main() -> None:
    """Entry point for ``image-triage-gui``."""
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.gui.host,
        port=settings.gui.port,
        log_level=settings.app.log_level.lower(),
    )


if __name__ == "__main__":
    main()
