"""Phase 8 tests: FastAPI GUI smoke tests, filters, overrides and jobs."""

from __future__ import annotations

import runpy
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
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


def test_empty_library_auto_scans_and_reports_no_active_job(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "auto.db"},
            "models": {"enabled": False},
        },
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/jobs"

    job = _wait_for_terminal_job(client, settings)
    assert job["kind"] == "scan"
    assert job["status"] == "completed", job
    assert job["result"]["scored"] == 4

    library = client.get("/")
    assert library.status_code == 200
    assert b"Library is out of date" not in library.content
    assert b"No analysis yet" not in library.content


def test_stale_library_reports_new_changed_and_missing(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        (photo_dir / "added.jpg").write_bytes((photo_dir / "burst_sharp.jpg").read_bytes())
        (photo_dir / "sub" / "other.jpg").unlink()

        response = client.get("/")
        assert response.status_code == 200
        assert b"Library is out of date" in response.content
        assert b"1 missing" in response.content

        scanned = client.post("/scan", follow_redirects=False)
        assert scanned.status_code == 303
        job = _wait_for_terminal_job(client, settings)
        assert job["kind"] == "scan" and job["status"] == "completed", job

        repository = Repository.open(settings.database_path)
        try:
            paths = {photo.path for photo in repository.all_photos()}
        finally:
            repository.close()
        assert "sub/other.jpg" not in paths
        assert "added.jpg" in paths

        assert client.get("/").status_code == 200
        assert b"Library is out of date" not in client.get("/").content


def test_scan_job_scores_without_a_separate_select(photo_dir: Path, tmp_path: Path) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "score.db"},
            "models": {"enabled": False},
        },
    )
    with TestClient(create_app(settings)) as client:
        client.post("/scan", follow_redirects=False)
        job = _wait_for_terminal_job(client, settings)
        assert job["status"] == "completed", job

        repository = Repository.open(settings.database_path)
        try:
            photos = repository.all_photos()
        finally:
            repository.close()
        assert len(photos) == 4
        assert all(photo.rating > 0 for photo in photos)
        assert all(photo.group_id is not None for photo in photos)
        assert all(photo.event_id is not None for photo in photos)


def test_duplicate_scan_requests_do_not_start_parallel_jobs(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        repository.create_job("scan", {})
    finally:
        repository.close()

    with client:
        response = client.get("/", follow_redirects=False)
        # An active job suppresses the auto-scan redirect.
        assert response.status_code == 200

        blocked = client.post("/scan", follow_redirects=False)
        assert blocked.status_code == 303
        assert blocked.headers["location"] == "/jobs"

    repository = Repository.open(settings.database_path)
    try:
        scans = [job for job in repository.list_jobs() if job["kind"] == "scan"]
    finally:
        repository.close()
    assert len(scans) == 1


def test_multi_select_rating_filter_returns_both_values(photo_dir: Path, tmp_path: Path) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "multi.db"},
            "models": {"enabled": False},
        },
    )
    with TestClient(create_app(settings)) as client:
        client.post("/scan", follow_redirects=False)
        _wait_for_terminal_job(client, settings)

        repository = Repository.open(settings.database_path)
        try:
            ratings = sorted({photo.rating for photo in repository.all_photos()})
        finally:
            repository.close()
        assert len(ratings) >= 1

        all_ids = client.get("/api/photo-ids").json()["ids"]
        assert len(all_ids) == 4

        # Selecting every rating at once must return every photo.
        query = "&".join(f"rating={value}" for value in ratings)
        multi = client.get(f"/api/photo-ids?{query}").json()
        assert sorted(multi["ids"]) == sorted(all_ids)

        # A single value returns strictly fewer, proving the values are not merged.
        single = client.get(f"/api/photo-ids?rating={ratings[0]}").json()
        assert 0 < single["total"] <= len(all_ids)

        # A combination that matches nothing is still a valid, non-error response.
        none = client.get("/api/photo-ids?rating=5&min_score=0.99").json()
        assert none["total"] == 0


def test_empty_filter_fields_do_not_return_a_validation_error(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        response = client.get(
            "/?rating=&event_id=&group_id=&label=&blur=&date_from=&date_to="
            "&min_score=&score_max=&sharpness_min=&aesthetic_min=&subject_min="
            "&camera_make=&camera_model=&q=&sort=&order=&page="
        )
        assert response.status_code == 200
        assert b"detail" not in response.content
        assert b"No photos found." not in response.content
        assert b"4 photos" in response.content


def test_filters_combine_and_sorting_is_applied(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        repository = Repository.open(settings.database_path)
        try:
            photos = repository.all_photos()
        finally:
            repository.close()

        # Combine a rating with a score floor that cannot exclude anything.
        top_rating = max(photo.rating for photo in photos)
        combined = client.get(f"/api/photo-ids?rating={top_rating}&min_score=0")
        assert combined.status_code == 200
        expected = [photo.id for photo in photos if photo.rating == top_rating]
        assert sorted(combined.json()["ids"]) == sorted(expected)
        assert combined.json()["total"] == len(expected)

        # A contradictory combination is a valid, empty result rather than an error.
        contradictory = client.get(f"/api/photo-ids?rating={top_rating}&min_score=0.99")
        assert contradictory.status_code == 200
        assert contradictory.json()["total"] <= len(expected)

        # Sorting is applied and the direction changes the order.
        descending = client.get("/?sort=score&order=desc").content
        ascending = client.get("/?sort=score&order=asc").content
        assert descending != ascending
        assert b'<option value="score" selected' in descending
        assert b'<option value="desc" selected' in descending
        assert b'<option value="asc" selected' in ascending


def test_photo_ids_endpoint_spans_every_page(photo_dir: Path, tmp_path: Path, monkeypatch) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    monkeypatch.setattr("image_triage.gui.app.PER_PAGE", 1)
    with client:
        first_page = client.get("/?sort=path").content
        assert b"page=2" in first_page
        all_ids = client.get("/api/photo-ids").json()
        assert all_ids["total"] == 4
        assert all_ids["ids"] != []


def test_media_is_served_concurrently_and_reports_missing_files(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        photo = repository.all_photos()[0]
    finally:
        repository.close()

    with client:
        first = client.get(f"/media/{photo.id}")
        assert first.status_code == 200
        assert first.headers["cache-control"] == "public, max-age=604800"

        # A second request runs in a different threadpool worker and closes the connection
        # that the first one created.
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: client.get(f"/media/{photo.id}"), range(8)))
        assert all(response.status_code == 200 for response in responses)

        assert client.get("/media/999999").status_code == 404

        repository = Repository.open(settings.database_path)
        try:
            repository.upsert_photo(
                Photo(path="missing.jpg", digest="f" * 64, taken=datetime(2024, 1, 1, tzinfo=UTC))
            )
            orphan = repository.photo_by_path("missing.jpg")
        finally:
            repository.close()
        assert orphan is not None and orphan.id is not None
        assert client.get(f"/media/{orphan.id}").status_code == 404


def test_setup_switches_library_root(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    other = tmp_path / "other-library"
    other.mkdir()

    with client:
        form = client.get("/setup")
        assert form.status_code == 200
        assert str(photo_dir) in form.text
        assert settings.database_path.name in form.text

        invalid = client.post("/setup", data={"root": str(tmp_path / "nope")})
        assert invalid.status_code == 400
        assert b"not a directory" in invalid.content

        switched = client.post("/setup", data={"root": str(other)}, follow_redirects=False)
        assert switched.status_code == 303
        assert client.get("/health").json()["input"] == str(other.resolve())
        assert client.get("/setup").status_code == 200


def test_setup_rejects_root_change_while_a_job_is_active(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        job_id = repository.create_job("analyze", {})
        repository.update_job(job_id, status="running")
    finally:
        repository.close()

    other = tmp_path / "blocked-library"
    other.mkdir()
    with client:
        response = client.post("/setup", data={"root": str(other)})
        assert response.status_code == 409
        assert b"job is active" in response.content
        assert client.get("/health").json()["input"] == str(photo_dir.resolve())


def test_scan_skips_tool_and_cache_directories(tmp_path: Path) -> None:
    from PIL import Image

    from image_triage.io.scan import find_images

    def write(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.zeros((20, 20, 3), np.uint8)).save(path)

    root = tmp_path / "project"
    write(root / "keep.jpg")
    for excluded in (
        ".venv/lib/python3.13/site-packages",
        ".git",
        "htmlcov",
        "__pycache__",
        ".mypy_cache",
        "node_modules/pkg",
        "build",
        ".image-triage",
    ):
        write(root / excluded / "tool.png")

    found = find_images(root)
    assert [path.name for path in found] == ["keep.jpg"]


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
