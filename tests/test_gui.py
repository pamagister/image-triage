"""Phase 8 tests: FastAPI GUI smoke tests, filters, overrides and jobs."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from image_triage.analysis.analyze import analyze_library
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


def test_events_page_and_job_runner(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        assert client.get("/events").status_code == 200
        assert client.get("/jobs").status_code == 200
        response = client.post(
            "/jobs/start", data={"kind": "select", "top_n": "1"}, follow_redirects=False
        )
        assert response.status_code == 303

        deadline = time.monotonic() + 15
        job = None
        while time.monotonic() < deadline:
            jobs = client.get("/jobs").status_code
            assert jobs == 200
            repository = Repository.open(settings.database_path)
            try:
                latest = repository.list_jobs()
            finally:
                repository.close()
            if latest and latest[0]["status"] in {"completed", "failed"}:
                job = latest[0]
                break
            time.sleep(0.1)
        assert job is not None
        assert job["status"] == "completed", job
        assert job["result"]["selected"] == 1
