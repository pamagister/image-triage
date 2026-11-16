"""Phase 4 tests: library filters, folder view, tri-state selection and tile metadata."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from image_triage.analysis.analyze import analyze_library
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.gui.app import create_app
from image_triage.selection.presets import FILTER_FIELDS, load_presets
from image_triage.selection.profiles import load_profiles


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
        assert b'name="view" value="folders"' in page.content
        css = Path("src/image_triage/gui/static/style.css").read_text()
        assert "align-items: flex-start;" in css


def test_library_sidebar_has_tabs_ranges_presets_and_filter_chips(
    photo_dir: Path, tmp_path: Path
) -> None:
    with _client(photo_dir, tmp_path) as client:
        page = client.get("/?view=folders&tab=filters&rating=4&blur_min=0.6&group_size_min=2")
        assert page.status_code == 200
        assert b'id="sidebar-folders"' in page.content
        assert b'id="sidebar-filters"' in page.content
        assert b'name="sharpness_min"' in page.content
        assert b'name="blur_max"' in page.content
        assert b'name="group_size_min"' in page.content
        assert b"Good" in page.content and b"Blurry" in page.content
        assert b'class="chip"' in page.content
        assert b'class="chip-label"' in page.content
        assert b'class="chip-value"' in page.content
        assert b'class="chip-remove"' in page.content
        assert b"data-dual-range" in page.content
        assert b"data-range-min" in page.content
        assert b"data-range-max" in page.content
        assert b'class="checkbox-row rating-row"' in page.content
        assert b'class="checkbox-row blur-row"' in page.content

        script = Path("src/image_triage/gui/static/selection.js").read_text()
        assert "data-range-min" in script and "data-range-max" in script
        assert "low > high" in script

        css = Path("src/image_triage/gui/static/style.css").read_text()
        assert "grid-template-columns: minmax(260px, 320px) 1fr;" in css
        assert "position: sticky;" in css
        assert "pointer-events: none;" in css
        assert "pointer-events: auto;" in css


def test_default_view_is_folders_and_flat_view_is_available(
    photo_dir: Path, tmp_path: Path
) -> None:
    with _client(photo_dir, tmp_path) as client:
        folders = client.get("/")
        assert b"folder-tree" in folders.content
        assert b"Flat tiles" in folders.content and b"Folder tree" in folders.content

        flat = client.get("/?view=flat")
        assert flat.status_code == 200
        assert b"view=flat" in flat.content
        assert b"folder-tree" in flat.content  # the sidebar tree remains available

        folders_explicit = client.get("/?view=folders")
        assert folders_explicit.status_code == 200
        assert b"folder-tree" in folders_explicit.content
        assert b'data-folder="."' in folders_explicit.content
        assert b'data-folder="sub"' in folders_explicit.content
        assert f">{photo_dir.name}</a>".encode() in folders_explicit.content
        assert f'title="{photo_dir.resolve()}"'.encode() in folders_explicit.content


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


def test_folder_tree_exposes_filter_checkboxes_and_toggle(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        page = client.get("/?view=folders")
        assert b"data-folder-node" in page.content
        assert b"data-folder-filter" in page.content
        assert b"data-select-photo" in page.content
        assert b'data-root="' in page.content
        assert b"<details open>" in page.content


def test_selection_controls_offer_add_deselect_and_confirm_clear(
    photo_dir: Path, tmp_path: Path
) -> None:
    with _client(photo_dir, tmp_path) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert b"data-deselect-all" in page.content
        assert b"Clear all" in page.content

        script = Path("src/image_triage/gui/static/selection.js").read_text()
        assert "unionSelected" in script
        assert "subtractSelected" in script
        assert "window.confirm" in script


def test_root_folder_filter_aggregates_descendants(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        response = client.get(
            "/",
            params={
                "view": "folders",
                "root": str(photo_dir.resolve()),
                "folder": ".",
                "page": 1,
            },
        )
        assert response.status_code == 200
        assert b"No photos found" not in response.content
        assert b"4 photos" in response.content


def test_root_folder_disables_folder_restriction(photo_dir: Path, tmp_path: Path) -> None:
    with _client(photo_dir, tmp_path) as client:
        response = client.get(
            "/",
            params=[
                ("view", "folders"),
                ("root", str(photo_dir.resolve())),
                ("folder", "sub"),
                ("folder", "."),
                ("min_score", "0"),
                ("page", "1"),
            ],
        )
        assert response.status_code == 200
        assert b"4 photos" in response.content


def test_folder_filter_keeps_full_tree_and_aggregated_counts(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
    finally:
        repository.close()

    repository = Repository.open(settings.database_path)
    try:
        items = repository.folder_counts(root=str(photo_dir.resolve()))
    finally:
        repository.close()
    counts = {item["folder"]: item["count"] for item in items}
    assert counts["."] == 4
    assert counts["sub"] == 1

    with client:
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
        assert b'data-count="4"' in response.content
        assert b'data-count="1"' in response.content


def test_multiple_folder_filter_returns_union(photo_dir: Path, tmp_path: Path) -> None:
    from datetime import datetime

    from tests.conftest import _scene, save_jpeg

    save_jpeg(
        photo_dir / "other" / "second.jpg",
        _scene(3),
        datetime(2024, 1, 1, 20, 0, 4),
    )
    settings, client = _client_with_settings(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
    finally:
        repository.close()

    with client:
        response = client.get(
            "/",
            params=[
                ("view", "folders"),
                ("root", str(photo_dir.resolve())),
                ("folder", "sub"),
                ("folder", "other"),
                ("page", "1"),
            ],
        )
        assert response.status_code == 200
        assert b"2 photos" in response.content


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


def test_settings_page_shows_root_counts_and_read_only_database(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    with client:
        page = client.get("/settings")
        assert page.status_code == 200
        assert str(photo_dir.resolve()) in page.text
        assert b'name="enabled_roots"' in page.content
        assert b'name="root_paths"' in page.content
        assert b'data-remove-root="' in page.content
        assert b"State database" in page.content
        assert str(settings.database_path).encode() in page.content
        assert b'data-disk-count="4"' in page.content
        assert b'data-analyzed-count="0"' in page.content
        assert b'name="filter_groups"' in page.content
        assert b"Visible filter groups" in page.content
        assert b">Selection</h2>" in page.content
        assert b">Export</h2>" in page.content
        assert b">Analysis</h2>" in page.content
        assert b">Scoring</h2>" in page.content
        assert b">Advanced</h2>" in page.content
        assert b'name="profile_name"' in page.content
        assert b'name="profile_top_n"' in page.content
        assert b'name="profile_order"' in page.content
        assert b"data-move-up" in page.content
        assert b'name="preset_enabled"' in page.content
        assert b'name="preset_values"' in page.content
        assert b"preset_overrides" not in page.content
        assert b'name="export_destination"' in page.content
        assert b"data-header-jobs" in page.content


def test_settings_page_persists_roots_and_tile_fields(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    with client:
        page = client.get("/settings")
        assert page.status_code == 200
        assert str(photo_dir.resolve()) in page.text

        response = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve())],
                "enabled_roots": [str(photo_dir.resolve())],
                "exclude": ".hidden, cache",
                "tile_fields": ["score", "taken"],
                "filter_groups": ["rating", "date"],
                "filter_groups_submitted": "true",
                "filter_hide_rejected": "true",
                "filter_hide_rejected_submitted": "true",
                "selection_prefer_accepted": "true",
                "profile_order": ["best50"],
                "profile_name": ["best50"],
                "profile_top_n": ["12"],
                "profile_diversity": ["0.7"],
                "profile_max_per_group": ["1"],
                "profile_max_per_day": ["4"],
                "profile_max_per_cluster": ["2"],
                "profile_event_quota": ["equal"],
                "preset_order": ["good"],
                "preset_name": ["good"],
                "preset_label": ["Good"],
                "preset_values": [
                    f"{key}="
                    + ("4,5" if key == "rating" else "0.6" if key == "aesthetic_min" else "")
                    for key in FILTER_FIELDS
                ],
                "preset_enabled": ["good"],
                "preset_submitted": "true",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.app.state.settings.input.roots == [photo_dir.resolve()]
        assert client.app.state.settings.input.disabled_roots == []
        assert client.app.state.settings.gui.tile_fields == ["score", "taken"]
        assert client.app.state.settings.gui.filters.visible == ["rating", "date"]
        assert client.app.state.settings.gui.filters.hide_rejected is True
        assert client.app.state.settings.selection.profile == "best50"
        assert client.app.state.settings.selection.prefer_accepted is True
        assert client.app.state.settings.gui.filters.presets == ["good"]
        assert client.app.state.settings.input.exclude == [".hidden", "cache"]

        assert load_profiles(client.app.state.settings)[0].top_n == 12
        assert load_presets(client.app.state.settings)[0].overrides == {
            "rating": [4, 5],
            "aesthetic_min": 0.6,
        }

        stored = client.app.state.settings.config_path.read_text()
        assert str(photo_dir.resolve()) in stored

        unrelated = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve())],
                "enabled_roots": [str(photo_dir.resolve())],
                "exclude": ".hidden",
            },
            follow_redirects=False,
        )
        assert unrelated.status_code == 303
        assert client.app.state.settings.gui.filters.visible == ["rating", "date"]
        assert client.app.state.settings.gui.filters.hide_rejected is True


def test_settings_adds_profiles_and_presets(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    profiles = load_profiles(settings)
    presets = load_presets(settings)

    with client:
        response = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve())],
                "enabled_roots": [str(photo_dir.resolve())],
                **_profile_form(profiles),
                **_preset_form(presets),
                "add_profile": "1",
                "add_preset": "1",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    profile_names = [profile.name for profile in load_profiles(client.app.state.settings)]
    preset_names = [preset.name for preset in load_presets(client.app.state.settings)]
    assert profile_names[-1] == "new-profile"
    assert preset_names[-1] == "new-preset"
    assert load_presets(client.app.state.settings)[-1].overrides == {}


def test_settings_removes_profiles_and_presets(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    profiles = load_profiles(settings)
    presets = load_presets(settings)

    with client:
        response = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve())],
                "enabled_roots": [str(photo_dir.resolve())],
                **_profile_form(profiles[1:]),
                **_preset_form(presets[1:], enabled=[]),
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    active_settings = client.app.state.settings
    assert [profile.name for profile in load_profiles(active_settings)] == [
        profile.name for profile in profiles[1:]
    ]
    assert [preset.name for preset in load_presets(active_settings)] == [
        preset.name for preset in presets[1:]
    ]
    assert active_settings.selection.profile == profiles[1].name
    assert active_settings.gui.filters.presets == []


def test_settings_ranks_and_renames_profiles_and_presets(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    profiles = load_profiles(settings)
    presets = load_presets(settings)
    ordered_profiles = list(reversed(profiles))
    profile_order = [profile.name for profile in ordered_profiles]
    ordered_profiles[0] = replace(ordered_profiles[0], name="top-profile")
    ordered_presets = [presets[1], presets[0]]
    preset_order = [preset.name for preset in ordered_presets]
    ordered_presets[0] = replace(ordered_presets[0], name="renamed-preset")

    with client:
        response = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve())],
                "enabled_roots": [str(photo_dir.resolve())],
                **_profile_form(ordered_profiles, order_names=profile_order),
                **_preset_form(
                    ordered_presets,
                    order_names=preset_order,
                    enabled=[preset_order[0]],
                ),
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    active_settings = client.app.state.settings
    assert active_settings.selection.profile == "top-profile"
    assert [profile.name for profile in load_profiles(active_settings)] == [
        "top-profile",
        *profile_order[1:],
    ]
    assert [preset.name for preset in load_presets(active_settings)] == [
        "renamed-preset",
        preset_order[1],
    ]
    assert active_settings.gui.filters.presets == ["renamed-preset"]


def test_settings_adds_deactivates_and_removes_roots(photo_dir: Path, tmp_path: Path) -> None:
    other = tmp_path / "other-library"
    other.mkdir()
    settings, client = _client_with_settings(photo_dir, tmp_path)

    with client:
        added = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve())],
                "enabled_roots": [str(photo_dir.resolve())],
                "add_root": "1",
                "new_root": str(other),
            },
            follow_redirects=False,
        )
        assert added.status_code == 303
        assert client.app.state.settings.input.roots == [
            photo_dir.resolve(),
            other.resolve(),
        ]
        assert client.app.state.settings.watched_roots == [
            photo_dir.resolve(),
            other.resolve(),
        ]

        deactivated = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve()), str(other)],
                "enabled_roots": [str(photo_dir.resolve())],
            },
            follow_redirects=False,
        )
        assert deactivated.status_code == 303
        assert client.app.state.settings.input.disabled_roots == [other.resolve()]
        assert client.app.state.settings.watched_roots == [photo_dir.resolve()]

        removed = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve()), str(other)],
                "enabled_roots": [str(photo_dir.resolve())],
                "remove_root": str(other),
            },
            follow_redirects=False,
        )
        assert removed.status_code == 303
        assert client.app.state.settings.input.roots == [photo_dir.resolve()]
        assert client.app.state.settings.input.disabled_roots == []

        repository = Repository.open(client.app.state.settings.database_path)
        try:
            states = {item["path"]: item["enabled"] for item in repository.roots()}
        finally:
            repository.close()
        assert states[str(other)] is False


def test_settings_requires_an_active_root(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    with client:
        response = client.post(
            "/settings",
            data={
                "root_paths": [str(photo_dir.resolve())],
                "enabled_roots": [],
            },
        )
        assert response.status_code == 400
        assert b"at least one watched root must be active" in response.content


def test_browse_api_lists_directories_and_rejects_files(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    with client:
        response = client.get("/api/browse", params={"path": str(photo_dir)})
        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == str(photo_dir.resolve())
        assert {item["name"] for item in payload["directories"]} == {"sub"}

        invalid = client.get("/api/browse", params={"path": str(photo_dir / "burst_sharp.jpg")})
        assert invalid.status_code == 400


def test_settings_rejects_changes_while_a_job_is_active(photo_dir: Path, tmp_path: Path) -> None:
    settings, client = _client_with_settings(photo_dir, tmp_path)
    repository = Repository.open(settings.database_path)
    try:
        repository.update_job(repository.create_job("scan", {}), status="running")
    finally:
        repository.close()
    with client:
        response = client.post(
            "/settings",
            data={
                "root_paths": [str(tmp_path)],
                "enabled_roots": [str(tmp_path)],
            },
        )
        assert response.status_code == 409
        assert b"job is active" in response.content


def _profile_form(profiles, order_names=None):
    data = {
        "profile_order": [],
        "profile_name": [],
        "profile_top_n": [],
        "profile_diversity": [],
        "profile_max_per_group": [],
        "profile_max_per_day": [],
        "profile_max_per_cluster": [],
        "profile_event_quota": [],
    }
    for index, profile in enumerate(profiles):
        data["profile_order"].append(
            order_names[index] if order_names is not None else profile.name
        )
        data["profile_name"].append(profile.name)
        data["profile_top_n"].append(str(profile.top_n))
        data["profile_diversity"].append(str(profile.diversity))
        data["profile_max_per_group"].append(str(profile.max_per_group))
        data["profile_max_per_day"].append(str(profile.max_per_day))
        data["profile_max_per_cluster"].append(str(profile.max_per_cluster))
        data["profile_event_quota"].append(profile.event_quota)
    return data


def _preset_form(presets, order_names=None, enabled=None):
    data = {
        "preset_order": [],
        "preset_name": [],
        "preset_label": [],
        "preset_values": [],
        "preset_enabled": list(enabled or []),
        "preset_submitted": "true",
    }
    for index, preset in enumerate(presets):
        data["preset_order"].append(order_names[index] if order_names is not None else preset.name)
        data["preset_name"].append(preset.name)
        data["preset_label"].append(preset.label)
        for key in FILTER_FIELDS:
            value = preset.overrides.get(key)
            if value is None:
                rendered = ""
            elif isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, list):
                rendered = ",".join(str(item) for item in value)
            else:
                rendered = str(value)
            data["preset_values"].append(f"{key}={rendered}")
    return data


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


def test_selection_review_panel_and_status_controls_are_available(
    photo_dir: Path, tmp_path: Path
) -> None:
    with _client(photo_dir, tmp_path) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert b"data-open-review" in page.content
        assert b"data-accept-selected" in page.content
        assert b"data-reject-selected" in page.content
        assert b"data-accept-filtered" in page.content
        assert b"data-reject-filtered" in page.content
        assert b'id="review-dialog"' in page.content
        assert b"data-review-grid" in page.content
        assert b'name="status" value="accepted"' in page.content

        script = Path("src/image_triage/gui/static/selection.js").read_text()
        assert "/api/photos" in script
        assert "/api/status" in script
        assert "renderReview" in script
        assert "stale id(s) removed" in script
