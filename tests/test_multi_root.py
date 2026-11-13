"""Phase 1-2 tests: appdata, central configuration, schema migration and multi-root scans."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from image_triage.analysis.analyze import analyze_library, scan_plan
from image_triage.core import appdata
from image_triage.core.models import Metrics, Photo
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.db.schema import INITIAL_SCHEMA, METRICS_V2
from tests.conftest import _scene, save_jpeg


def _settings(roots: list[Path], db: Path):
    return load_settings(
        None,
        {
            "input": {"roots": roots, "db_path": db},
            "models": {"enabled": False},
        },
    )


def test_appdata_directories_follow_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMAGE_TRIAGE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("IMAGE_TRIAGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("IMAGE_TRIAGE_CACHE_DIR", str(tmp_path / "cache"))
    assert appdata.config_dir() == tmp_path / "config"
    assert appdata.data_dir() == tmp_path / "data"
    assert appdata.cache_dir() == tmp_path / "cache"
    assert appdata.config_file() == tmp_path / "config" / "config.yaml"
    assert appdata.database_file() == tmp_path / "data" / "triage.db"
    assert appdata.cache_subdir("previews") == tmp_path / "cache" / "previews"
    assert appdata.default_export_root() == tmp_path / "data" / "exports"


def test_central_config_is_overridden_by_project_env_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "central"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "scoring": {"sharpness_weight": 0.3},
                "input": {"roots": [str(tmp_path / "central-root")]},
                "gui": {"default_view": "folders"},
            }
        )
    )
    project = tmp_path / "image-triage.yaml"
    project.write_text(yaml.safe_dump({"scoring": {"sharpness_weight": 0.5}}))
    monkeypatch.setenv("IMAGE_TRIAGE_CONFIG_DIR", str(config_dir))

    central = load_settings(None)
    assert central.scoring.sharpness_weight == 0.3
    assert central.gui.default_view == "folders"

    project_wins = load_settings(project)
    assert project_wins.scoring.sharpness_weight == 0.5
    assert project_wins.gui.default_view == "folders"

    monkeypatch.setenv("IMAGE_TRIAGE_SCORING__SHARPNESS_WEIGHT", "0.7")
    assert load_settings(project).scoring.sharpness_weight == 0.7
    assert (
        load_settings(project, {"scoring": {"sharpness_weight": 0.9}}).scoring.sharpness_weight
        == 0.9
    )


def _v2_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(INITIAL_SCHEMA)
    connection.executescript(METRICS_V2)
    connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '2')")
    now = datetime.now(UTC).isoformat()
    for photo_id, (name, rating) in enumerate([("a.jpg", 4), ("b.jpg", 2), ("c.jpg", 3)], start=1):
        connection.execute(
            "INSERT INTO photos (id, path, digest, taken, width, height, score, rating, "
            "flags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)",
            (photo_id, name, "d" * 64 if photo_id < 3 else "e" * 64, now, 10, 10, 0.5, rating, now),
        )
        connection.execute(
            "INSERT INTO metrics (photo_id, sharpness, sharpness_raw, blur_kind, blur_confidence, "
            "composition, composition_components, aesthetic, aesthetic_source, subject_score, "
            "subject_rarity, exposure, metric_version) "
            "VALUES (?, 0.5, 100, 'none', 0, 0.5, '{}', 0.5, 'heuristic', 0, 0, 0, '1.1.0')",
            (photo_id,),
        )
    connection.commit()
    connection.close()


def test_v2_database_migrates_to_content_addressed_v3(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _v2_database(path)

    repository = Repository.open(path)
    try:
        version = repository.connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        assert version == "3"
        # Duplicate digest collapses to one content row; both paths remain locations.
        assert repository.count_content() == 2
        assert repository.count_photos() == 3
        assert repository.photo_by_path("a.jpg").rating == 4
        assert {photo.path for photo in repository.all_photos()} == {"a.jpg", "b.jpg", "c.jpg"}
        assert repository.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        repository.close()


def _photo(path: str, digest: str, *, root: str = "", rating: int = 0) -> Photo:
    return Photo(
        path=path,
        root_path=root,
        digest=digest,
        taken=datetime(2024, 1, 1, tzinfo=UTC),
        metrics=Metrics(sharpness=0.5),
        rating=rating,
    )


def test_content_identity_shares_metrics_across_locations(tmp_path: Path) -> None:
    repository = Repository.open(tmp_path / "state.db")
    try:
        first = _photo("a.jpg", "a" * 64, root=str(tmp_path / "one"), rating=4)
        repository.upsert_photo(first, update_rating=True)
        second = _photo("b.jpg", "a" * 64, root=str(tmp_path / "two"))
        repository.upsert_photo(second)

        assert repository.count_content() == 1
        assert repository.count_photos() == 2
        locations = repository.all_photos()
        assert {photo.path for photo in locations} == {"a.jpg", "b.jpg"}
        assert {photo.rating for photo in locations} == {4}
        assert {photo.root_path for photo in locations} == {
            str(tmp_path / "one"),
            str(tmp_path / "two"),
        }
    finally:
        repository.close()


def test_moved_file_keeps_content_and_location_id(tmp_path: Path) -> None:
    repository = Repository.open(tmp_path / "state.db")
    try:
        root = str(tmp_path)
        photo = _photo("old.jpg", "a" * 64, root=root, rating=5)
        repository.upsert_photo(photo, update_rating=True)
        location = repository.location_paths()[(root, "old.jpg")]
        keep = {(root, "new.jpg")}

        new_id = repository.upsert_scanned_location(
            photo.id,
            root,
            "new.jpg",
            digest="a" * 64,
            keep=keep,
            analyzed_at=datetime.now(UTC).isoformat(),
        )
        assert new_id == location["id"]
        assert repository.location_paths().keys() == {(root, "new.jpg")}
        assert repository.photo_by_path("new.jpg").rating == 5
    finally:
        repository.close()


def test_missing_location_is_marked_unavailable_without_losing_rating(tmp_path: Path) -> None:
    repository = Repository.open(tmp_path / "state.db")
    try:
        root = str(tmp_path)
        repository.upsert_photo(_photo("a.jpg", "a" * 64, root=root, rating=5), update_rating=True)
        removed = repository.mark_missing_locations(set())
        assert removed == [f"{tmp_path}/a.jpg"]
        assert repository.count_photos() == 0
        assert repository.count_content() == 1
        assert repository.photo_by_path("a.jpg") is None
        assert repository.all_content()[0].rating == 5
    finally:
        repository.close()


def test_changed_file_repoints_location_to_new_content(tmp_path: Path) -> None:
    repository = Repository.open(tmp_path / "state.db")
    try:
        root = str(tmp_path)
        repository.upsert_photo(_photo("a.jpg", "a" * 64, root=root, rating=5), update_rating=True)
        repository.upsert_photo(_photo("a.jpg", "b" * 64, root=root))
        assert repository.count_content() == 2
        assert repository.count_photos() == 1
        assert repository.photo_by_path("a.jpg").digest == "b" * 64
    finally:
        repository.close()


def test_two_roots_analyze_unique_content_once_and_record_both_locations(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    pixels = _scene(3)
    save_jpeg(first / "same.jpg", pixels, datetime(2024, 1, 1))
    save_jpeg(second / "copy.jpg", pixels, datetime(2024, 1, 1))
    save_jpeg(first / "other.jpg", _scene(4), datetime(2024, 1, 1))

    settings = _settings([first, second], tmp_path / "multi.db")
    repository = Repository.open(settings.database_path)
    try:
        result = analyze_library(settings, repository)
        assert result.total == 3
        assert result.analyzed == 2
        assert result.reused == 1
        assert repository.count_content() == 2
        assert repository.count_photos() == 3
        assert (
            repository.photo_by_path("same.jpg").digest
            == repository.photo_by_path("copy.jpg").digest
        )
        assert {(photo.root_path, photo.path) for photo in repository.all_photos()} == {
            (str(first), "same.jpg"),
            (str(second), "copy.jpg"),
            (str(first), "other.jpg"),
        }
    finally:
        repository.close()


def test_disabled_roots_are_excluded_and_repository_tracks_active_state(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    base = _settings([first, second], tmp_path / "disabled.db")
    settings = base.model_copy(
        update={"input": base.input.model_copy(update={"disabled_roots": [second]})}
    )
    assert settings.watched_roots == [first.resolve()]

    repository = Repository.open(settings.database_path)
    try:
        repository.sync_roots([first, second], enabled=[first])
        states = {item["path"]: item["enabled"] for item in repository.roots()}
        assert states[str(first)] is True
        assert states[str(second)] is False

        repository.sync_roots([first], enabled=[first])
        states = {item["path"]: item["enabled"] for item in repository.roots()}
        assert states[str(first)] is True
        assert states[str(second)] is False
    finally:
        repository.close()


def test_nested_roots_are_de_overlapped(tmp_path: Path) -> None:
    parent = tmp_path / "photos"
    child = parent / "2024"
    child.mkdir(parents=True)
    save_jpeg(parent / "a.jpg", _scene(1), datetime(2024, 1, 1))
    save_jpeg(child / "b.jpg", _scene(2), datetime(2024, 1, 1))

    settings = _settings([parent, child], tmp_path / "nested.db")
    plan = scan_plan(settings)
    assert plan == [(parent, sorted(plan[0][1]))]
    assert {path.relative_to(parent).as_posix() for path in plan[0][1]} == {
        "2024/b.jpg",
        "a.jpg",
    }

    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
        assert repository.count_photos() == 2
        assert {photo.root_path for photo in repository.all_photos()} == {str(parent)}
    finally:
        repository.close()


def test_moved_changed_and_missing_files_are_reconciled_on_rescan(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    save_jpeg(root / "moved.jpg", _scene(5), datetime(2024, 1, 1))
    save_jpeg(root / "changed.jpg", _scene(6), datetime(2024, 1, 1))
    save_jpeg(root / "gone.jpg", _scene(7), datetime(2024, 1, 1))
    settings = _settings([root], tmp_path / "reconcile.db")
    repository = Repository.open(settings.database_path)
    try:
        analyze_library(settings, repository)
        digest = repository.photo_by_path("moved.jpg").digest
        content_id = repository.photo_by_path("moved.jpg").id

        (root / "moved.jpg").rename(root / "renamed.jpg")
        save_jpeg(root / "changed.jpg", _scene(8), datetime(2024, 1, 2))
        (root / "gone.jpg").unlink()
        result = analyze_library(settings, repository)

        assert result.missing == [f"{root}/gone.jpg"]
        assert repository.photo_by_path("renamed.jpg").digest == digest
        assert repository.photo_by_path("renamed.jpg").id == content_id
        assert repository.photo_by_path("moved.jpg") is None
        assert repository.count_content() == 4
        assert repository.count_photos() == 2
        assert (
            repository.location_paths(available_only=False)[(str(root), "gone.jpg")]["available"]
            is False
        )
    finally:
        repository.close()
