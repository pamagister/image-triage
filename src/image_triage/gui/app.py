"""Local FastAPI web GUI for browsing, comparing and curating a library."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from image_triage.analysis.analyze import analyze_library
from image_triage.analysis.pipeline import run_pipeline
from image_triage.core.models import ExportMode, OverrideSource, Photo
from image_triage.core.settings import Settings, load_settings
from image_triage.db.repository import Repository
from image_triage.export.export import export_photos
from image_triage.export.previews import preview_path
from image_triage.io.scan import find_images

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
    root = _input_root(settings)
    preview = preview_path(photo, root / ".image-triage" / "previews")
    path = preview if preview.is_file() else root / photo.path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
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


def _run_job(settings: Settings, job_id: int, kind: str, payload: dict[str, Any]) -> None:
    repository = Repository.open(settings.database_path)
    last_progress = 0.0
    try:
        repository.update_job(job_id, status="running", progress=0.05)
        root = _input_root(settings)
        output = root / ".image-triage" / "gui-runs" / str(job_id)

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

        if kind == "analyze":
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
            latest = repository.latest_selection_run()
            if latest is None:
                raise ValueError("no selection found; run select first")
            photos = repository.get_selection(latest.id)
            if not photos:
                raise ValueError("latest selection is empty; run select again")
            exported = export_photos(photos, root, output, ExportMode(settings.report.export_mode))
            summary = {"exported": len(exported), "output": str(output)}
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

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        repo: Repository = Depends(repository),
        rating: int | None = None,
        event_id: int | None = None,
        label: str | None = None,
        q: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_score: float | None = None,
        sort: str = "taken",
        page: int = 1,
    ) -> HTMLResponse:
        filters = {
            "rating": rating,
            "event_id": event_id,
            "label": label,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "min_score": min_score,
            "search": q,
        }
        total = repo.count_photos(**filters)
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(max(1, page), pages)
        photos = repo.list_photos(
            **filters, sort=sort, limit=PER_PAGE, offset=(page - 1) * PER_PAGE
        )
        latest = repo.latest_run()
        filter_values = {
            "rating": rating,
            "event_id": event_id,
            "label": label,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "min_score": min_score,
            "sort": sort,
        }
        base_query = urlencode(
            [
                (key, value.isoformat() if isinstance(value, date) else str(value))
                for key, value in filter_values.items()
                if value is not None and value != ""
            ]
        )
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "photos": photos,
                "events": repo.events(),
                "total": total,
                "page": page,
                "pages": pages,
                "sort": sort,
                "latest_run": latest,
                "filters": {
                    "rating": rating,
                    "event_id": event_id,
                    "label": label,
                    "q": q,
                    "date_from": date_from,
                    "date_to": date_to,
                    "min_score": min_score,
                },
                "base_query": base_query,
                "active_jobs": _active_jobs(repo),
            },
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
