"""Phase 4 tests: library filters, folder view, tri-state selection and tile metadata."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from image_triage.analysis.analyze import analyze_library
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.gui.app import create_app


def _client(photo_dir: Path, tmp_path: Path, **gui: object):
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "ui.db"},
            "models": {"enabled": False},
            "gui": {"host": "127.0.0.1", "port": 8765, **gui},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
    finally:
        repository.close()
    return TestClient(create_app(settings))


def test_filters_are_top_aligned_in_one_block(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert b'class="filters"' in page.content
        assert b'name="view" value="flat"' in page.content
        css = Path("src/image_triage/gui/static/style.css").read_text()
        assert "align-items: flex-start;" in css


def test_default_view_is_flat_and_folder_view_is_available(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        flat = client.get("/")
        assert b"folder-tree" not in flat.content
        assert b"Flat tiles" in flat.content and b"Folder tree" in flat.content

        folders = client.get("/?view=folders")
        assert folders.status_code == 200
        assert b"folder-tree" in folders.content
        assert b'data-folder="."' in folders.content
        assert b'data-folder="sub"' in folders.content
        assert f">{photo_dir.name}</a>".encode() in folders.content
        assert f'title="{photo_dir.resolve()}"'.encode() in folders.content


def test_folder_counts_respect_active_filters(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        all_folders = client.get("/?view=folders").content
        assert b'data-folder="sub"' in all_folders

        filtered = client.get("/?view=folders&q=burst")
        assert filtered.status_code == 200
        assert b'data-folder="."' in filtered.content
        assert b'data-folder="sub"' not in filtered.content


def test_folder_tree_link_applies_folder_filter(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        response = client.get(
            "/",
            params={
                "view": "folders",
                "root": str(photo_dir.resolve()),
                "folder": "sub",
                "page": 1,
            },
        )
        assert response.status_code == 200
        assert b'data-folder="."' in response.content
        assert b'data-folder="sub"' in response.content


def test_folder_rows_expose_tri_state_selection_data(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        page = client.get("/?view=folders")
        assert b"data-folder-select" in page.content
        assert b"data-select-photo" in page.content
        assert b'data-root="' in page.content


def test_tile_first_line_is_file_name_and_path_is_below(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        page = client.get("/").text
        name = page.index('<div class="name">burst_sharp.jpg</div>')
        path = page.index('<div class="path"', name)
        assert name < path
        assert str(photo_dir.resolve()) in page


def test_tile_metadata_follows_settings(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path, tile_fields=["score"]) as client:
        page = client.get("/").text
        meta = page[page.index('<div class="meta">') :]
        meta = meta[: meta.index("</li>")]
        assert ">score " in meta
        assert ">rating " not in meta
        assert ">taken " not in meta


def test_settings_page_persists_roots_and_tile_fields(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    with client:
        page = client.get("/settings")
        assert page.status_code == 200
        assert str(photo_dir.resolve()) in page.text

        response = client.post(
            "/settings",
            data={
                "roots": str(photo_dir.resolve()),
                "exclude": ".hidden, cache",
                "tile_fields": ["score", "taken"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.app.state.settings.input.roots == [photo_dir.resolve()]
        assert client.app.state.settings.gui.tile_fields == ["score", "taken"]
        assert client.app.state.settings.input.exclude == [".hidden", "cache"]

        stored = client.app.state.settings.config_path.read_text()
        assert str(photo_dir.resolve()) in stored


def test_settings_rejects_changes_while_a_job_is_active(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        repository.update_job(repository.create_job("scan", {}), status="running")
    finally:
        repository.close()
    with client:
        response = client.post("/settings", data={"roots": str(tmp_path)})
        assert response.status_code == 409
        assert b"job is active" in response.content


def _client_with_settings(photo_dir: Path, tmp_path: Path):
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "settings.db"},
            "models": {"enabled": False},
        },
    )
    return settings, TestClient(create_app(settings))


def test_flat_export_resolves_collisions_and_tree_export_keeps_paths(
    photo_dir: Path, tmp_path: Path
) -> None:
    first = tmp_path / "root1"
    second = tmp_path / "root2"
    first.mkdir()
    second.mkdir()
    from datetime import datetime

    from tests.conftest import _scene, save_jpeg

    save_jpeg(first / "same.jpg", _scene(11), datetime(2024, 1, 1))
    save_jpeg(second / "same.jpg", _scene(12), datetime(2024, 1, 1))
    settings = load_settings(
        None,
        {
            "input": {"roots": [first, second], "db_path": tmp_path / "export.db"},
            "models": {"enabled": False},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
    finally:
        repository.close()

    flat = tmp_path / "flat-out"
    with TestClient(create_app(settings)) as client:
        client.post("/scan", follow_redirects=False)
        _wait(client, settings)
        response = client.post(
            "/export",
            data={"scope": "filtered", "output": str(flat), "layout": "flat"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert _wait(client, settings)["status"] == "completed"
    assert sorted(path.name for path in flat.iterdir()) == ["same.jpg", "same_1.jpg"]

    tree = tmp_path / "tree-out"
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/export",
            data={"scope": "filtered", "output": str(tree), "layout": "tree"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert _wait(client, settings)["status"] == "completed"
    assert sorted(
        path.relative_to(tree).as_posix() for path in tree.rglob("*") if path.is_file()
    ) == [
        "same.jpg",
        "same_1.jpg",
    ]


def test_rerender_resizes_and_keeps_exif(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    target = tmp_path / "rendered"
    with client:
        client.post("/scan", follow_redirects=False)
        _wait(client, settings)
        response = client.post(
            "/export",
            data={
                "scope": "filtered",
                "output": str(target),
                "rerender": "true",
                "max_long_edge": "100",
                "jpeg_quality": "80",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert _wait(client, settings)["status"] == "completed"
    from PIL import Image

    rendered = sorted(target.glob("*.jpg"))
    assert rendered
    with Image.open(rendered[0]) as image:
        assert max(image.size) <= 100
        assert image.getexif().get_ifd(0x8769).get(36867)


def _wait(client: TestClient, settings, timeout: float = 15.0) -> dict:
    import time

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
    raise AssertionError("job did not finish")
