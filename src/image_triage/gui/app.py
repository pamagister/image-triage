"""Local FastAPI web GUI for browsing, comparing and curating a library."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

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

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
PER_PAGE = 60


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


def _run_job(settings: Settings, job_id: int, kind: str, payload: dict[str, Any]) -> None:
    repository = Repository.open(settings.database_path)
    try:
        repository.update_job(job_id, status="running", progress=0.1)
        root = _input_root(settings)
        output = root / ".image-triage" / "gui-runs" / str(job_id)
        if kind == "analyze":
            result = analyze_library(settings, repository)
            summary = result.to_dict()
        elif kind == "select":
            result = run_pipeline(
                settings,
                repository,
                output=output,
                top_n=int(payload.get("top_n", settings.selection.top_n)),
                export=False,
            )
            summary = result.to_dict()
        elif kind == "export":
            latest = repository.latest_run()
            photos = repository.get_selection(latest.id) if latest else []
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
    settings = settings or load_settings()
    app = FastAPI(title="Image Triage", version="1.0")
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def repository() -> Repository:
        repo = Repository.open(settings.database_path)
        try:
            yield repo
        finally:
            repo.close()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "input": str(_input_root(settings))}

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        repo: Repository = Depends(repository),
        rating: int | None = None,
        event_id: int | None = None,
        label: str | None = None,
        q: str | None = None,
        sort: str = "taken",
        page: int = 1,
    ) -> HTMLResponse:
        filters = {
            "rating": rating,
            "event_id": event_id,
            "label": label,
            "search": q,
        }
        total = repo.count_photos(**filters)
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(max(1, page), pages)
        photos = repo.list_photos(
            **filters, sort=sort, limit=PER_PAGE, offset=(page - 1) * PER_PAGE
        )
        latest = repo.latest_run()
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
                "filters": {"rating": rating, "event_id": event_id, "label": label, "q": q},
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
            {"photo": photo, "similar": similar, "overrides": repo.get_overrides()},
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
        points = []
        for photo in repo.all_photos():
            if photo.gps_lat is not None and photo.gps_lon is not None:
                points.append(
                    {
                        "lat": photo.gps_lat,
                        "lon": photo.gps_lon,
                        "label": photo.path,
                        "id": photo.id,
                    }
                )
        if points:
            min_lat = min(point["lat"] for point in points)
            max_lat = max(point["lat"] for point in points)
            min_lon = min(point["lon"] for point in points)
            max_lon = max(point["lon"] for point in points)
            lat_span = max(1e-9, max_lat - min_lat)
            lon_span = max(1e-9, max_lon - min_lon)
            for point in points:
                point["x"] = (point["lon"] - min_lon) / lon_span * 100
                point["y"] = (max_lat - point["lat"]) / lat_span * 100
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
        repo: Repository = Depends(repository),
        kind: str = Form(...),
        top_n: int = Form(200),
    ) -> RedirectResponse:
        job_id = repo.create_job(kind, {"top_n": top_n})
        thread = threading.Thread(
            target=_run_job,
            args=(settings, job_id, kind, {"top_n": top_n}),
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
    def media(photo_id: int, repo: Repository = Depends(repository)) -> FileResponse:
        photo = repo.photo_by_id(photo_id)
        if photo is None:
            raise HTTPException(404, "photo not found")
        path = _media_path(settings, photo)
        if not path.is_file():
            raise HTTPException(404, "photo file not found")
        return FileResponse(path)

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
