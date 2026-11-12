"""Phase 8 tests: FastAPI GUI smoke tests, filters, overrides and jobs."""

from __future__ import annotations

import runpy
import time
from pathlib import Path

from fastapi.testclient import TestClient

from image_triage.analysis.analyze import analyze_library
from image_triage.core.models import Photo
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.gui.app import create_app


def _settings(photo_dir: Path, tmp_path: Path):
    return load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "state.db"},
            "models": {"enabled": False},
            "gui": {"host": "127.0.0.1", "port": 8765},
        },
    )


def _prepared_client(photo_dir: Path, tmp_path: Path):
    settings = _settings(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
    finally:
        repository.close()
    return settings, TestClient(create_app(settings))


def _wait_for_terminal_job(client: TestClient, settings, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        repository = Repository.open(settings.database_path)
        try:
            jobs = repository.list_jobs()
        finally:
            repository.close()
        if jobs and jobs[0]["status"] in {"completed", "failed"}:
            return jobs[0]
        time.sleep(0.1)
    raise AssertionError("job did not reach a terminal state")


def test_module_entrypoint_starts_same_server(photo_dir: Path, tmp_path: Path, monkeypatch) -> None:
    settings = _settings(photo_dir, tmp_path)
    calls: dict[str, object] = {}

    def fake_run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("image_triage.gui.app.load_settings", lambda: settings)
    runpy.run_module("image_triage.gui", run_name="__main__")
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8765


def test_library_index_and_photo_detail(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        index = client.get("/")
        assert index.status_code == 200
        assert b"burst_sharp.jpg" in index.content

        repository = Repository.open(settings.database_path)
        try:
            photo = repository.all_photos()[0]
        finally:
            repository.close()

        detail = client.get(f"/photo/{photo.id}")
        assert detail.status_code == 200
        assert b"Sharpness" in detail.content

        media = client.get(f"/media/{photo.id}")
        assert media.status_code == 200
        assert media.headers["content-type"].startswith("image/")

        compare = client.get(f"/compare?ids={photo.id}")
        assert compare.status_code == 200


def test_filters_and_override_persist(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        filtered = client.get("/?rating=5")
        assert filtered.status_code == 200
        repository = Repository.open(settings.database_path)
        try:
            photo = repository.all_photos()[0]
        finally:
            repository.close()

        response = client.post(
            f"/photo/{photo.id}/override",
            data={"rating": "4", "keep": "keep"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        repository = Repository.open(settings.database_path)
        try:
            overrides = repository.get_overrides()
        finally:
            repository.close()
        assert overrides[0].photo_id == photo.id
        assert overrides[0].rating == 4
        assert overrides[0].keep is True

        detail = client.get(f"/photo/{photo.id}")
        assert b"Current:" in detail.content
        assert b"rating 4" in detail.content
        assert b'<option value="4" selected>' in detail.content


def test_filters_and_pagination_preserve_query(
    photo_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    monkeypatch.setattr("image_triage.gui.app.PER_PAGE", 1)
    with client:
        filtered = client.get(
            "/?q=burst&date_from=2024-01-01&date_to=2024-01-01&min_score=0&sort=score"
        )
        assert filtered.status_code == 200
        assert b"page=2" in filtered.content
        for fragment in (
            b"q=burst",
            b"date_from=2024-01-01",
            b"date_to=2024-01-01",
            b"min_score=0.0",
            b"sort=score",
        ):
            assert fragment in filtered.content

        empty = client.get("/?date_from=2024-01-02")
        assert empty.status_code == 200
        assert b"No photos found." in empty.content


def test_events_scatter_handles_single_point(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        repository.upsert_photo(Photo(path="gps.jpg", digest="g" * 64, gps_lat=1.0, gps_lon=2.0))
    finally:
        repository.close()

    with client:
        response = client.get("/events")
        assert response.status_code == 200
        assert b"gps.jpg" in response.content
        assert b'cx="50.00"' in response.content
        assert b'cy="50.00"' in response.content


def test_events_page_and_job_runner(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        assert client.get("/events").status_code == 200
        assert client.get("/jobs").status_code == 200

        empty_export = client.post(
            "/jobs/start", data={"kind": "export", "top_n": "1"}, follow_redirects=False
        )
        assert empty_export.status_code == 303
        failed = _wait_for_terminal_job(client, settings)
        assert failed["status"] == "failed"
        assert "no selection found" in failed["result"]["error"]

        response = client.post(
            "/jobs/start", data={"kind": "select", "top_n": "1"}, follow_redirects=False
        )
        assert response.status_code == 303

        job = _wait_for_terminal_job(client, settings)
        assert job["status"] == "completed", job
        assert job["result"]["selected"] == 1

        response = client.post(
            "/jobs/start", data={"kind": "export", "top_n": "1"}, follow_redirects=False
        )
        assert response.status_code == 303
        exported = _wait_for_terminal_job(client, settings)
        assert exported["status"] == "completed", exported
        assert exported["result"]["exported"] == 1
