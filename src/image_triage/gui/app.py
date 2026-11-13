"""Local FastAPI web GUI for browsing, comparing and curating a library."""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from image_triage.analysis.analyze import analyze_library
from image_triage.analysis.pipeline import run_pipeline
from image_triage.core.models import BlurKind, ExportMode, OverrideSource, Photo
from image_triage.core.settings import Settings, load_settings
from image_triage.db.repository import Repository
from image_triage.export.export import export_photos
from image_triage.export.previews import preview_path
from image_triage.grouping.build import build_groups_and_events
from image_triage.gui.library_status import library_status
from image_triage.gui.query import parse_photo_query
from image_triage.io.scan import find_images
from image_triage.scoring.score import score_library

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
PER_PAGE = 60

#: Jobs that write to the state database and therefore block a library-root change.
ACTIVE_JOB_STATUSES = ("pending", "running")
MEDIA_CACHE_CONTROL = "public, max-age=604800"


def _current_settings(request: Request) -> Settings:
    """Settings of the running app, including a library root chosen in the GUI."""
    return request.app.state.settings


def _input_root(settings: Settings) -> Path:
    return Path(settings.input.root).expanduser().resolve()


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


def _count_files(root: Path, exclude: tuple[str, ...]) -> int:
    """Number of supported images below ``root`` after configured exclusions."""
    if not root.is_dir():
        return 0
    excluded = tuple(root / name for name in exclude)
    return len(find_images(root, excluded))


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
            params.append((key, value))
    params.extend([("sort", query.sort), ("order", query.order)])
    if "view" not in overrides:
        params.append(("view", query.view))
    params.extend((key, value) for key, value in overrides.items() if value is not None)
    if query.search:
        params.insert(0, ("q", query.search))
    return "/?" + urlencode(params)


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
        elif kind == "export":
            mode = ExportMode(payload.get("mode", settings.report.export_mode))
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
        return {"ok": True, "input": str(_input_root(_current_settings(request)))}

    @app.get("/setup", response_class=HTMLResponse)
    def setup_form(request: Request) -> HTMLResponse:
        settings = _current_settings(request)
        root = _input_root(settings)
        return TEMPLATES.TemplateResponse(
            request,
            "setup.html",
            {
                "root": root,
                "root_exists": root.is_dir(),
                "file_count": _count_files(root, tuple(settings.input.exclude)),
                "database_path": settings.database_path,
                "error": request.query_params.get("error"),
            },
        )

    @app.post("/setup", response_model=None)
    def setup(
        request: Request,
        repo: Repository = Depends(repository),
        root: str = Form(...),
    ) -> HTMLResponse | RedirectResponse:
        """Switch the library root; rejected while a job reads or writes the state database."""
        settings = _current_settings(request)
        candidate = Path(root).expanduser()
        if not candidate.is_dir():
            return TEMPLATES.TemplateResponse(
                request,
                "setup.html",
                {
                    "root": candidate,
                    "root_exists": False,
                    "file_count": 0,
                    "database_path": settings.database_path,
                    "error": f"not a directory: {candidate}",
                },
                status_code=400,
            )
        active = _active_jobs(repo)
        if active:
            running = ", ".join(f"{job['kind']} #{job['id']}" for job in active)
            return TEMPLATES.TemplateResponse(
                request,
                "setup.html",
                {
                    "root": _input_root(settings),
                    "root_exists": True,
                    "file_count": _count_files(
                        _input_root(settings), tuple(settings.input.exclude)
                    ),
                    "database_path": settings.database_path,
                    "error": f"cannot change the library while a job is active: {running}",
                },
                status_code=409,
            )
        app.state.settings = settings.model_copy(
            update={"input": settings.input.model_copy(update={"root": candidate.resolve()})}
        )
        return RedirectResponse("/", status_code=303)

    def _library_response(
        request: Request,
        repo: Repository,
        *,
        error: str = "",
        status_code: int = 200,
    ) -> HTMLResponse:
        """Render the library page with the current filters and an optional message."""
        query = parse_photo_query(request.query_params)
        filters = dict(query.filters)
        if query.search:
            filters["search"] = query.search
        total = repo.count_photos(**filters)
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(max(1, query.page), pages)
        # The tree is navigation: ignore the folder selection so every node stays visible.
        tree_filters = {key: value for key, value in filters.items() if key != "folder"}
        folders = repo.folder_counts(**tree_filters)
        for item in folders:
            folder = None if item["folder"] == "." else item["folder"]
            item["url"] = _url_with(
                query,
                view="folders",
                root=item["root"],
                folder=folder,
                page=1,
            )
            item["depth"] = 0 if item["folder"] == "." else item["folder"].count("/") + 1
        tree = _folder_tree(folders)
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
                "view_flat": _url_with(query, view="flat", folder=None, page=1),
                "view_folders": _url_with(query, view="folders", page=1),
                "folders": tree,
                "selected_folders": set(filters.get("folder", [])),
                "tile_fields": _current_settings(request).gui.tile_fields,
                "active_jobs": _active_jobs(repo),
                "status": library_status(_current_settings(request), repo),
                "filter_options": repo.filter_options(),
                "error": error,
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

    @app.post("/export", response_model=None)
    def start_export(
        request: Request,
        repo: Repository = Depends(repository),
        scope: str = Form("selected"),
        output: str = Form(""),
        mode: str = Form(""),
        photo_ids: str = Form(""),
        layout: str = Form(""),
        rerender: bool = Form(False),
        max_long_edge: str = Form(""),
        jpeg_quality: str = Form(""),
    ) -> HTMLResponse | RedirectResponse:
        """Export either the checked photos or the current filtered view as a background job."""
        settings = _current_settings(request)
        roots = settings.watched_roots
        query = parse_photo_query(request.query_params)
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
            if repo.count_photos(**filters) == 0:
                return _export_error(request, repo, "no photos match the current filters")
            export_payload = {"filters": filters}

        export_mode = mode or settings.export.mode
        payload: dict[str, Any] = {
            "output": str(target),
            "mode": export_mode,
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
        query = parse_photo_query(request.query_params)
        filters = dict(query.filters)
        if query.search:
            filters["search"] = query.search
        ids = repo.photo_ids(**filters)
        return {"ids": ids, "total": len(ids)}

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

    @app.get("/settings", response_class=HTMLResponse)
    def settings_form(request: Request, repo: Repository = Depends(repository)) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "settings.html",
            {
                "settings": _current_settings(request),
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
                "active_jobs": _active_jobs(repo),
                "error": request.query_params.get("error"),
            },
        )

    @app.post("/settings", response_model=None)
    def save_settings(
        request: Request,
        repo: Repository = Depends(repository),
        roots: str = Form(""),
        exclude: str = Form(""),
        default_view: str = Form("flat"),
        tile_fields: list[str] = Form([]),  # noqa: B008
        export_mode: str = Form("copy"),
        export_layout: str = Form("flat"),
        rerender: bool = Form(False),
        max_long_edge: str = Form(""),
        jpeg_quality: int = Form(85),
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
        active = _active_jobs(repo)
        if active:
            return TEMPLATES.TemplateResponse(
                request,
                "settings.html",
                {
                    "settings": settings,
                    "tile_field_options": [],
                    "active_jobs": active,
                    "error": "cannot change settings while a job is active",
                },
                status_code=409,
            )
        data = settings.model_dump(mode="json")
        root_paths = [line.strip() for line in roots.splitlines() if line.strip()]
        data["input"]["roots"] = root_paths
        data["input"]["exclude"] = [item.strip() for item in exclude.split(",") if item.strip()]
        data["gui"]["default_view"] = default_view
        data["gui"]["tile_fields"] = tile_fields or []
        data["export"].update(
            {
                "mode": export_mode,
                "layout": export_layout,
                "rerender": rerender,
                "max_long_edge": int(max_long_edge) if max_long_edge.strip() else None,
                "jpeg_quality": jpeg_quality,
            }
        )
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
            return TEMPLATES.TemplateResponse(
                request,
                "settings.html",
                {
                    "settings": settings,
                    "tile_field_options": [],
                    "active_jobs": [],
                    "error": str(exc),
                },
                status_code=400,
            )
        path = updated.config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            yaml.safe_dump(updated.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        request.app.state.settings = updated
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/events", response_class=HTMLResponse)
    def events(request: Request, repo: Repository = Depends(repository)) -> HTMLResponse:
        event_list = repo.events()
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
            {"events": event_list, "points": points},
        )

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request, repo: Repository = Depends(repository)) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "jobs.html", {"jobs": repo.list_jobs()})

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

    @app.post("/jobs/start")
    def start_job(
        request: Request,
        repo: Repository = Depends(repository),
        kind: str = Form(...),
        top_n: int = Form(200),
    ) -> RedirectResponse:
        job_id = repo.create_job(kind, {"top_n": top_n})
        thread = threading.Thread(
            target=_run_job,
            args=(_current_settings(request), job_id, kind, {"top_n": top_n}),
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
