"""Phase 1 tests: settings precedence, database migration/repository and CLI doctor."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from image_triage.cli.app import app
from image_triage.core.models import (
    BlurKind,
    Detection,
    Event,
    Metrics,
    OverrideSource,
    Photo,
    Run,
    RunStatus,
    Selection,
)
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository


def test_settings_precedence_cli_env_yaml_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "image-triage.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "scoring": {"sharpness_weight": 0.5},
                "input": {"root": str(tmp_path)},
            }
        )
    )
    settings = load_settings(config)
    assert settings.scoring.sharpness_weight == 0.5
    assert settings.scoring.composition_weight == 0.25  # default

    monkeypatch.setenv("IMAGE_TRIAGE_SCORING__SHARPNESS_WEIGHT", "0.7")
    settings = load_settings(config)
    assert settings.scoring.sharpness_weight == 0.7

    settings = load_settings(config, {"scoring": {"sharpness_weight": 0.9}})
    assert settings.scoring.sharpness_weight == 0.9
    assert settings.input.root == tmp_path


def test_settings_validate_weights_and_fingerprint(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_settings(
            None,
            {
                "scoring": {
                    "sharpness_weight": 0,
                    "composition_weight": 0,
                    "aesthetic_weight": 0,
                    "subject_weight": 0,
                }
            },
        )
    first = load_settings(None, {"scoring": {"sharpness_weight": 0.5}})
    second = load_settings(None, {"scoring": {"sharpness_weight": 0.5}})
    assert first.fingerprint() == second.fingerprint()
    assert first.database_path.name == "triage.db"


def test_fresh_database_has_wal_and_schema(tmp_path: Path) -> None:
    repository = Repository.open(tmp_path / "state.db")
    try:
        version = repository.connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        assert version == "3"
        assert repository.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert repository.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert repository.count_photos() == 0
    finally:
        repository.close()


def test_connection_is_usable_from_another_thread(tmp_path: Path) -> None:
    """FastAPI closes a request-scoped repository in a different threadpool worker."""
    repository = Repository.open(tmp_path / "state.db")
    try:
        repository.upsert_photo(_photo())
        results: list[int] = []

        def read_rows() -> None:
            results.append(repository.count_photos())

        thread = threading.Thread(target=read_rows)
        thread.start()
        thread.join()
        assert results == [1]
    finally:
        repository.close()


def _photo(path: str = "a.jpg", digest: str | None = None) -> Photo:
    import hashlib

    return Photo(
        path=path,
        digest=digest or hashlib.sha256(path.encode()).hexdigest(),
        taken=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
        width=100,
        height=80,
        gps_lat=1.5,
        gps_lon=2.5,
        metrics=Metrics(
            sharpness=0.8,
            blur_kind=BlurKind.NONE,
            composition=0.7,
            composition_components={"thirds": 0.9},
            aesthetic=0.6,
            subject_score=0.5,
        ),
        detections=[Detection("person", 0.9, (0.1, 0.1, 0.5, 0.6))],
        embedding=[0.6, 0.8],
        score=0.7,
        rating=4,
        flags=["ok"],
    )


def test_repository_round_trips_photos_metrics_detections(tmp_path: Path) -> None:
    repository = Repository.open(tmp_path / "state.db")
    try:
        photo = _photo()
        photo_id = repository.upsert_photo(photo)
        stored = repository.photo_by_id(photo_id)
        assert stored is not None
        assert stored.path == "a.jpg"
        assert stored.metrics.blur_kind is BlurKind.NONE
        assert stored.metrics.composition_components == {"thirds": 0.9}
        assert stored.detections[0].label == "person"
        assert stored.embedding == pytest.approx([0.6, 0.8])
        assert stored.gps_lat == 1.5

        # Re-upsert keeps the same id and replaces detections.
        photo.id = photo_id
        photo.detections = [Detection("dog", 0.5, (0.0, 0.0, 0.1, 0.1))]
        repository.upsert_photo(photo)
        stored = repository.photo_by_id(photo_id)
        assert [d.label for d in stored.detections] == ["dog"]
        assert repository.count_photos() == 1
    finally:
        repository.close()


def test_repository_filters_groups_events_and_selections(tmp_path: Path) -> None:
    repository = Repository.open(tmp_path / "state.db")
    try:
        first = _photo("a.jpg")
        second = _photo("b.jpg")
        first.rating, second.rating = 5, 2
        repository.upsert_photo(first)
        repository.upsert_photo(second)
        assert [p.path for p in repository.list_photos(rating=5)] == ["a.jpg"]
        assert len(repository.list_photos(min_score=0.0)) == 2

        repository.set_groups([(first.id, 1), (second.id, 1)])
        assert repository.photo_by_id(first.id).group_id == 1

        event = Event(
            start=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
            end=datetime(2024, 5, 1, 13, 0, tzinfo=UTC),
            label="walk",
            source="time",
            photo_count=2,
        )
        stored = repository.set_events([event], [])
        event_id = stored[0].id
        repository.assign_events([(first.id, event_id), (second.id, event_id)])
        assert repository.events()[0].label == "walk"
        assert repository.photo_by_id(second.id).event_id == event_id

        run = Run(
            id="run-1",
            command="select",
            started_at=datetime(2024, 5, 1, tzinfo=UTC),
            status=RunStatus.COMPLETED,
            counts={"selected": 1},
        )
        repository.save_run(run)
        repository.set_selection("run-1", [Selection(first.id, 1, 0.9, "best of group")])
        selected = repository.get_selection("run-1")
        assert [p.path for p in selected] == ["a.jpg"]
        assert selected[0].reason == "best of group"

        repository.set_override(second.id, rating=3, keep=True, source=OverrideSource.GUI)
        override = repository.get_overrides()[0]
        assert override.rating == 3 and override.keep is True

        job_id = repository.create_job("select", {"top_n": 1})
        repository.update_job(job_id, status="running", progress=0.5)
        assert repository.get_job(job_id)["progress"] == 0.5
    finally:
        repository.close()


def test_doctor_json_is_valid_and_exits_zero(tmp_path: Path) -> None:
    config = tmp_path / "image-triage.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "input": {"root": str(tmp_path)},
                "storage": {"data_dir": str(tmp_path / "appdata")},
                "models": {"enabled": False},
            }
        )
    )
    result = CliRunner().invoke(app, ["doctor", "--json", "--config", str(config)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["ok"] is True
    assert any(check["name"] == "database" and check["ok"] for check in report["checks"])
    assert (tmp_path / "appdata" / "triage.db").is_file()


def test_database_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '99')")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="newer"):
        Repository.open(path)
