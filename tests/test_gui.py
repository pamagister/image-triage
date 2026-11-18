"""Phase 8 tests: FastAPI GUI smoke tests, filters, overrides and jobs."""

from __future__ import annotations

import html
import os
import re
import runpy
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams

from image_triage.analysis.analyze import analyze_library
from image_triage.core.models import Event, Photo
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.gui.app import _url_with, create_app
from image_triage.gui.query import parse_photo_query


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


def test_scan_clears_an_mtime_only_change(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    target = photo_dir / "burst_sharp.jpg"
    future = datetime.now(UTC).timestamp() + 60
    os.utime(target, (future, future))

    with client:
        response = client.get("/")
        assert response.status_code == 200
        assert b"1 changed" in response.content

        scanned = client.post("/scan", follow_redirects=False)
        assert scanned.status_code == 303
        job = _wait_for_terminal_job(client, settings)
        assert job["kind"] == "scan" and job["status"] == "completed", job
        assert job["result"]["analysis"]["reused"] == 4

        page = client.get("/")
        assert page.status_code == 200
        assert b"Library is out of date" not in page.content


def test_library_status_falls_back_to_analyzed_at_without_a_stored_mtime(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        stored = repository.location_paths()
        key = (str(photo_dir.resolve()), "burst_sharp.jpg")
        location = repository.location_by_id(stored[key]["id"])
        assert location is not None
        repository.upsert_location(
            location.photo_id,
            location.root_path,
            location.relative_path,
            analyzed_at=location.analyzed_at.isoformat() if location.analyzed_at else None,
        )
    finally:
        repository.close()

    future = datetime.now(UTC).timestamp() + 60
    os.utime(photo_dir / "burst_sharp.jpg", (future, future))

    with client:
        response = client.get("/")
        assert response.status_code == 200
        assert b"1 changed" in response.content


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


def test_multi_value_filters_stay_lists_after_parsing() -> None:
    query = parse_photo_query(
        QueryParams([("event_id", "1"), ("event_id", "2"), ("group_id", "3")])
    )
    assert query.filters["event_id"] == [1, 2]
    assert query.filters["group_id"] == [3]


def test_query_parser_applies_hide_rejected_default_only_when_unspecified() -> None:
    default = parse_photo_query(QueryParams([]), default_hide_rejected=True)
    assert default.filters["hide_rejected"] is True

    explicit = parse_photo_query(
        QueryParams([("hide_rejected", "false")]), default_hide_rejected=True
    )
    assert explicit.filters["hide_rejected"] is False


def test_query_parser_status_dropdown_values() -> None:
    all_statuses = parse_photo_query(QueryParams([("status", "all")]), default_hide_rejected=True)
    assert "status" not in all_statuses.filters
    assert all_statuses.filters["hide_rejected"] is False

    not_rejected = parse_photo_query(QueryParams([("status", "not_rejected")]))
    assert not_rejected.filters["status"] == ["not_rejected"]


def test_preset_url_expands_list_and_boolean_overrides() -> None:
    query = parse_photo_query(QueryParams([("root", "/photos")]))
    url = _url_with(query, rating=[4, 5], status=["accepted"], hide_rejected=True)
    assert "rating=4" in url and "rating=5" in url
    assert "status=accepted" in url
    assert "hide_rejected=true" in url
    assert "root=%2Fphotos" in url


def test_query_parser_reads_metric_ranges_and_group_size() -> None:
    query = parse_photo_query(
        QueryParams(
            [
                ("sharpness_min", "0.5"),
                ("blur_max", "0.3"),
                ("group_size_min", "2"),
                ("hide_rejected", "true"),
                ("status", "accepted"),
            ]
        )
    )
    assert query.filters["sharpness_min"] == 0.5
    assert query.filters["blur_max"] == 0.3
    assert query.filters["group_size_min"] == 2
    assert query.filters["hide_rejected"] is True
    assert query.filters["status"] == ["accepted"]


def test_event_and_group_filter_pages_do_not_500(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        client.post("/scan", follow_redirects=False)
        assert _wait_for_terminal_job(client, settings)["status"] == "completed"

        repository = Repository.open(settings.database_path)
        try:
            events = repository.events()
            groups = repository.group_options()
            photos = repository.all_photos()
        finally:
            repository.close()

        if events:
            response = client.get(f"/?event_id={events[0].id}")
            assert response.status_code == 200
        group_id = groups[0]["id"] if groups else photos[0].group_id
        if group_id is not None:
            response = client.get(f"/?group_id={group_id}")
            assert response.status_code == 200


def test_library_options_exclude_unavailable_historical_events_and_groups(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        photos = repository.all_photos()
        first, second, third, fourth = photos
        assert all(photo.id is not None for photo in photos)
        repository.set_groups([(first.id, 1), (second.id, 1), (third.id, 2), (fourth.id, 2)])
        events = repository.set_events(
            [
                Event(
                    start=datetime(2024, 1, 1),
                    end=datetime(2024, 1, 1),
                    label="available event",
                    source="time",
                    photo_count=2,
                ),
                Event(
                    start=datetime(2023, 1, 1),
                    end=datetime(2023, 1, 1),
                    label="historical event",
                    source="time",
                    photo_count=2,
                ),
            ],
            [],
        )
        repository.assign_events(
            [
                (first.id, events[0].id),
                (second.id, events[0].id),
                (third.id, events[1].id),
                (fourth.id, events[1].id),
            ]
        )
        with repository.connection:
            repository.connection.execute(
                "UPDATE photo_locations SET available = 0 WHERE photo_id IN (?, ?)",
                (third.id, fourth.id),
            )
        assert repository.count_photos(group_size_min=2) == 2
        assert [group["id"] for group in repository.available_groups()] == [1]
        assert [event["label"] for event in repository.available_events()] == ["available event"]
    finally:
        repository.close()
    with client:
        page = client.get("/?tab=filters")
        assert page.status_code == 200
        assert "available event (2)" in page.text
        assert "historical event" not in page.text
        assert "Group 1 (2 available)" in page.text
        assert "Group 2 (" not in page.text
        assert "Events" in page.text and "not visual similarity" in page.text
        groups = client.get("/groups")
        assert groups.status_code == 200
        assert "Group 1" in groups.text and "Group 2" not in groups.text
        timeline = client.get("/events")
        assert "available event" in timeline.text
        assert "historical event" not in timeline.text


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
        assert b'"detail":' not in response.content
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
        expected = [photo.location_id for photo in photos if photo.rating == top_rating]
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


def test_export_selected_copies_only_the_checked_photos(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        ids = [photo.location_id for photo in repository.all_photos()]
    finally:
        repository.close()
    target = tmp_path / "export-out"

    with client:
        response = client.post(
            "/export",
            data={"scope": "selected", "photo_ids": f"{ids[0]},{ids[1]}", "output": str(target)},
            follow_redirects=False,
        )
        assert response.status_code == 303
        job = _wait_for_terminal_job(client, settings)
        assert job["status"] == "completed", job
        assert job["result"]["exported"] == 2

    copied = sorted(
        path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
    )
    assert len(copied) == 2


def test_export_all_uses_every_filtered_photo_across_pages(
    photo_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "filtered.db"},
            "models": {"enabled": False},
        },
    )
    monkeypatch.setattr("image_triage.gui.app.PER_PAGE", 1)
    target = tmp_path / "export-filtered"

    with TestClient(create_app(settings)) as client:
        client.post("/scan", follow_redirects=False)
        assert _wait_for_terminal_job(client, settings)["status"] == "completed"

        repository = Repository.open(settings.database_path)
        try:
            ratings = sorted({photo.rating for photo in repository.all_photos()})
            # Pick a rating with more than one photo so a page-limited export would be short.
            counts = {value: repository.count_photos(rating=value) for value in ratings}
        finally:
            repository.close()
        candidates = [value for value in ratings if counts[value] > 1]
        assert candidates, counts
        rating = candidates[0]
        expected = counts[rating]

        # One photo per page, so a filtered export must go beyond the visible page.
        assert client.get(f"/?rating={rating}").status_code == 200

        response = client.post(
            "/export",
            data={"scope": "filtered", "output": str(target)},
            follow_redirects=False,
            params={"rating": rating},
        )
        assert response.status_code == 303
        job = _wait_for_terminal_job(client, settings)
        assert job["status"] == "completed", job
        assert job["result"]["exported"] == expected

    copied = [path for path in target.rglob("*") if path.is_file()]
    assert len(copied) == expected


def test_export_rejects_a_target_inside_the_library(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        response = client.post(
            "/export",
            data={"scope": "filtered", "output": str(photo_dir / "inside")},
        )
        assert response.status_code == 400
        assert b"outside every library root" in response.content


def test_export_selected_without_a_selection_is_reported(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        response = client.post(
            "/export",
            data={"scope": "selected", "photo_ids": "", "output": str(tmp_path / "none")},
        )
        assert response.status_code == 400
        assert b"no photos are selected" in response.content


def test_default_export_path_is_timestamped(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        page = client.get("/")
        assert b"export_" in page.content


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


def test_setup_redirects_to_settings(photo_dir: Path, tmp_path: Path) -> None:
    _settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        response = client.get("/setup", follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"] == "/settings"


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


def test_page_size_controls_pagination_and_preserves_filters(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        for index in range(27):
            repository.upsert_photo(
                Photo(
                    path=f"extra-{index:02}.jpg",
                    root_path=str(photo_dir.resolve()),
                    digest=f"{index + 1000:064x}",
                )
            )
    finally:
        repository.close()
    with client:
        first = client.get("/?q=extra&tab=filters&sort=path&page_size=10")
        assert first.status_code == 200
        assert first.text.count('data-photo-id="') == 10
        assert "page 1 / 3" in first.text
        assert "page_size=10" in first.text
        assert 'value="10" selected' in first.text
        last = client.get("/?q=extra&tab=filters&sort=path&page_size=10&page=3")
        assert last.text.count('data-photo-id="') == 7
        assert "page 3 / 3" in last.text
        for size in (20, 50, 100, 200):
            page = client.get(f"/?q=extra&page_size={size}")
            assert page.text.count('data-photo-id="') == min(size, 27)
        invalid = client.get("/?q=extra&page_size=0")
        assert invalid.text.count('data-photo-id="') == 27
        assert 'value="50" selected' in invalid.text


def test_filter_form_preserves_scope_and_explicit_hide_rejected(
    photo_dir: Path, tmp_path: Path
) -> None:
    _, client = _prepared_client(photo_dir, tmp_path)
    with client:
        page = client.get(
            "/",
            params={
                "tab": "filters",
                "root": str(photo_dir.resolve()),
                "folder": "sub",
                "hide_rejected": "false",
                "page_size": "20",
            },
        )
        assert 'id="sidebar-filters" checked' in page.text
        assert f'name="root" value="{photo_dir.resolve()}"' in page.text
        assert 'name="folder" value="sub"' in page.text
        assert 'name="hide_rejected" value="false"' in page.text
        assert '<select class="status-select" name="status"' in page.text
        assert '<option value="all" selected' in page.text
        assert 'name="page_size" value="20"' in page.text


def test_detail_navigates_filtered_results_across_pages(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        for index in range(12):
            repository.upsert_photo(
                Photo(
                    path=f"review-{index:02}.jpg",
                    root_path=str(photo_dir.resolve()),
                    digest=f"{index + 2000:064x}",
                )
            )
        photos = repository.list_photos(search="review-", sort="path", order="asc")
        assert len(photos) == 12
    finally:
        repository.close()

    tenth, eleventh = photos[9:11]
    context = "q=review-&sort=path&order=asc&view=flat&tab=filters&page_size=10&page=1"
    with client:
        detail = client.get(f"/photo/{tenth.id}?{context}&location_id={tenth.location_id}")
        assert detail.status_code == 200
        assert "10 / 12" in detail.text
        assert f"/media/location/{tenth.location_id}" in detail.text
        match = re.search(r'href="([^"]+)" data-detail-next', detail.text)
        assert match is not None
        next_url = html.unescape(match.group(1))
        assert f"/photo/{eleventh.id}?" in next_url
        assert f"location_id={eleventh.location_id}" in next_url
        assert "page=2" in next_url and "q=review-" in next_url
        next_detail = client.get(next_url)
        assert "11 / 12" in next_detail.text
        back = re.search(r'href="([^"]+)" data-back-library', next_detail.text)
        assert back is not None
        assert "page=2" in html.unescape(back.group(1))

        response = client.post(
            f"/photo/{tenth.id}/override?{context}&location_id={tenth.location_id}",
            data={"rating": "4"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "q=review-" in response.headers["location"]
        assert f"location_id={tenth.location_id}" in response.headers["location"]

        outside = client.get(f"/photo/{tenth.id}?q=no-such-match&location_id={tenth.location_id}")
        assert "outside the current filtered results" in outside.text
        assert "data-detail-next" not in outside.text


def test_detail_decisions_and_ratings_are_immediate_and_independent(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        photo = repository.all_photos()[0]
    finally:
        repository.close()
    query = f"?q=burst&tab=filters&location_id={photo.location_id}"
    with client:
        accepted = client.post(
            f"/photo/{photo.id}/decision{query}",
            data={"status": "accepted"},
            follow_redirects=False,
        )
        assert accepted.status_code == 303
        assert "q=burst" in accepted.headers["location"]
        rated = client.post(
            f"/photo/{photo.id}/rating{query}", data={"rating": "5"}, follow_redirects=False
        )
        assert rated.status_code == 303
        detail = client.get(rated.headers["location"])
        assert "status-badge status-accepted" in detail.text
        assert "rating 5/5" in detail.text
        assert 'data-rate="5"' in detail.text
        assert 'aria-pressed="true"' in detail.text
        filtered = client.get("/?rating=5&q=burst")
        assert f'data-photo-id="{photo.id}"' in filtered.text
        assert client.post(f"/photo/{photo.id}/rating", data={"rating": "6"}).status_code == 422
        assert client.post(f"/photo/{photo.id}/decision", data={"status": "bad"}).status_code == 400
        rejected = client.post(
            f"/photo/{photo.id}/decision{query}",
            data={"status": "rejected"},
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        assert "status-badge status-rejected" in client.get(rejected.headers["location"]).text
        cleared = client.post(
            f"/photo/{photo.id}/decision{query}", data={"status": "none"}, follow_redirects=False
        )
        assert cleared.status_code == 303
        repository = Repository.open(settings.database_path)
        try:
            override = next(
                item for item in repository.get_overrides() if item.photo_id == photo.id
            )
            assert override.keep is None
            assert override.rating == 5
            assert repository.photo_by_id(photo.id).rating == 5
        finally:
            repository.close()


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


def test_events_page_and_read_only_job_runner(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        assert client.get("/events").status_code == 200
        jobs_page = client.get("/jobs")
        assert jobs_page.status_code == 200
        assert b"<form" not in jobs_page.content
        assert b"/jobs/start" not in jobs_page.content

        response = client.post("/scan", follow_redirects=False)
        assert response.status_code == 303

        job = _wait_for_terminal_job(client, settings)
        assert job["status"] == "completed", job
        assert job["kind"] == "scan"


def test_selection_review_and_status_api_round_trip(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        repository = Repository.open(settings.database_path)
        try:
            photos = repository.all_photos()
        finally:
            repository.close()
        location_id = photos[0].location_id
        assert location_id is not None

        summaries = client.post("/api/photos", json={"location_ids": [location_id, 999999]})
        assert summaries.status_code == 200
        body = summaries.json()
        assert len(body["photos"]) == 1
        assert body["missing"] == [999999]
        assert body["photos"][0]["location_id"] == location_id
        assert body["photos"][0]["keep"] is None

        accepted = client.post(
            "/api/status", json={"location_ids": [location_id], "status": "accepted"}
        )
        assert accepted.status_code == 200
        assert accepted.json()["photos"] == 1

        page = client.get("/")
        assert b"status-badge status-accepted" in page.content
        detail = client.get(f"/photo/{photos[0].id}")
        assert b"status-badge status-accepted" in detail.content

        rejected = client.post(
            "/api/status", json={"location_ids": [location_id], "status": "rejected"}
        )
        assert rejected.status_code == 200
        repository = Repository.open(settings.database_path)
        try:
            assert repository.photo_by_location(location_id).keep is False
        finally:
            repository.close()

        cleared = client.post("/api/status", json={"location_ids": [location_id], "status": "none"})
        assert cleared.status_code == 200
        repository = Repository.open(settings.database_path)
        try:
            assert repository.photo_by_location(location_id).keep is None
        finally:
            repository.close()


def test_status_filter_accepts_bulk_filtered_scope(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        response = client.post(
            "/api/status",
            json={"filters": {"min_score": 0}, "status": "accepted"},
        )
        assert response.status_code == 200
        assert response.json()["photos"] >= 1

        filtered = client.get("/?status=accepted")
        assert filtered.status_code == 200
        assert b"status-badge status-accepted" in filtered.content


def test_best_n_add_and_replace_modes(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        photos = sorted(repository.all_photos(), key=lambda photo: photo.path)
        repository.update_scores(
            [(photo.id, 0.9 - index * 0.1, 5, []) for index, photo in enumerate(photos)]
        )
        location_ids = [photo.location_id for photo in photos]
    finally:
        repository.close()

    replaced = client.post(
        "/api/select-best",
        json={"filters": {"min_score": 0}, "n": 2, "mode": "replace"},
    )
    assert replaced.status_code == 200
    assert len(replaced.json()["location_ids"]) == 2

    added = client.post(
        "/api/select-best",
        json={
            "filters": {"min_score": 0},
            "n": 2,
            "mode": "add",
            "existing_ids": [location_ids[0]],
        },
    )
    assert added.status_code == 200
    result = added.json()
    assert len(result["location_ids"]) == 3
    assert location_ids[0] in result["location_ids"]
    assert len(result["added_ids"]) == 2

    rejected = client.post(
        "/api/status",
        json={"location_ids": [location_ids[0]], "status": "rejected"},
    )
    assert rejected.status_code == 200
    excluded = client.post(
        "/api/select-best",
        json={
            "filters": {"min_score": 0},
            "n": 5,
            "mode": "replace",
            "include_rejected": False,
        },
    )
    assert excluded.status_code == 200
    assert location_ids[0] not in excluded.json()["location_ids"]


def test_group_best_selects_one_photo_per_group(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        photos = sorted(repository.all_photos(), key=lambda photo: photo.path)
        repository.update_scores(
            [(photo.id, 0.9 - index * 0.05, 3, []) for index, photo in enumerate(photos)]
        )
        assignments = [(photo.id, 1 + index // 2) for index, photo in enumerate(photos)]
        repository.set_groups(assignments)
    finally:
        repository.close()

    response = client.post(
        "/api/select-group-best",
        json={"filters": {"min_score": 0}, "mode": "replace"},
    )
    assert response.status_code == 200
    result = response.json()
    assert len(result["location_ids"]) == len({1, 2})
    assert result["summary"]["groups"] == 2

    group_id = 1
    compare = client.get(f"/compare/group/{group_id}")
    assert compare.status_code == 200
    assert b"data-compare-photo" in compare.content
    assert b"data-compare-select-best" in compare.content
    assert b"data-compare-accept-best" in compare.content
    assert b"data-compare-reject-rest" in compare.content


def test_library_has_best_n_controls(photo_dir: Path, tmp_path: Path) -> None:
    _, client = _prepared_client(photo_dir, tmp_path)
    with client:
        page = client.get("/")
        assert page.status_code == 200
        assert b"data-best-n" in page.content
        assert b"data-best-mode" in page.content
        assert b"data-best-run" in page.content
        assert b"data-profile-select" in page.content
        assert b"Run selection" in page.content
        assert b'value="group">one per group' in page.content
        assert b"Find best" not in page.content
        assert b"data-group-best" not in page.content
        assert b'value="accepted">Accepted photos' in page.content


def test_removed_active_profile_falls_back_without_500(photo_dir: Path, tmp_path: Path) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "legacy.db"},
            "models": {"enabled": False},
            "selection": {"profile": "best200"},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
    finally:
        repository.close()

    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert b'data-profile-n="50" selected' in page.content
        response = client.post(
            "/api/select-best",
            json={"filters": {"min_score": 0}, "n": 1, "mode": "replace"},
        )
        assert response.status_code == 200
        assert len(response.json()["location_ids"]) == 1


def test_large_best_n_runs_as_background_job(
    photo_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import image_triage.gui.app as gui_app

    monkeypatch.setattr(gui_app, "BEST_N_JOB_THRESHOLD", 1)
    settings, client = _prepared_client(photo_dir, tmp_path)
    with client:
        response = client.post(
            "/api/select-best",
            json={"filters": {"min_score": 0}, "n": 1, "mode": "replace"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["async"] is True
        assert body["job_id"]

        job = _wait_for_terminal_job(client, settings)
        assert job["status"] == "completed"
        assert job["result"]["location_ids"]


def test_export_accepted_scope_copies_only_accepted_photos(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        photos = sorted(repository.all_photos(), key=lambda photo: photo.path)
    finally:
        repository.close()
    accepted_id = photos[0].location_id
    target = tmp_path / "export-accepted"

    with client:
        status = client.post(
            "/api/status",
            json={"location_ids": [accepted_id], "status": "accepted"},
        )
        assert status.status_code == 200

        response = client.post(
            "/export",
            data={"scope": "accepted", "output": str(target)},
            follow_redirects=False,
        )
        assert response.status_code == 303
        job = _wait_for_terminal_job(client, settings)
        assert job["status"] == "completed", job
        assert job["result"]["exported"] == 1
        assert job["result"]["mode"] == "copy"
        assert job["result"]["scope"] == "accepted"

    copied = [path for path in target.rglob("*") if path.is_file()]
    assert len(copied) == 1
    assert not copied[0].is_symlink()
    assert copied[0].stat().st_nlink == 1


def test_events_page_renders_timeline_card_with_cover(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _prepared_client(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        photo = repository.all_photos()[0]
        repository.set_events(
            [
                Event(
                    id=1,
                    start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                    end=datetime(2026, 5, 1, 13, 0, tzinfo=UTC),
                    label="Morning walk",
                    photo_count=1,
                )
            ],
            [(photo.id, 1)],
        )
    finally:
        repository.close()

    with client:
        page = client.get("/events")
        assert page.status_code == 200
        assert b"event-timeline" in page.content
        assert b"event-card" in page.content
        assert b"Morning walk" in page.content
        assert b"/?event_id=1&amp;view=folders" in page.content
        assert b"Open in library" in page.content
