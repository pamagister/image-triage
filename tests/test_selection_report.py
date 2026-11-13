"""Phase 4 tests: profiles, quotas, selection, reports, previews and export."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from jsonschema import validate
from typer.testing import CliRunner

from image_triage.analysis.pipeline import run_pipeline
from image_triage.cli.app import app
from image_triage.core.models import Metrics, Photo, Run, RunStatus
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.report.csv_report import write_csv
from image_triage.report.json_report import build_report
from image_triage.selection.profiles import load_profile
from image_triage.selection.select import event_quotas, select_photos

T0 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def _photo(
    name: str,
    *,
    score: float,
    group: int,
    event: int,
    taken: datetime,
    embedding: list[float] | None = None,
) -> Photo:
    return Photo(
        path=name,
        taken=taken,
        embedding=embedding,
        score=score,
        group_id=group,
        event_id=event,
        metrics=Metrics(sharpness=score, composition=0.5, aesthetic=0.5),
    )


def test_profile_defaults_and_overrides() -> None:
    settings = load_settings(None)
    profile = load_profile(settings)
    assert profile.top_n == 200
    assert profile.event_quota == "sainte_lague"
    profile = load_profile(settings, overrides={"top_n": 7, "diversity": 0.1})
    assert profile.top_n == 7 and profile.diversity == 0.1


def test_profile_rejects_unknown_name(tmp_path: Path) -> None:
    settings = load_settings(
        None,
        {"input": {"root": tmp_path}, "selection": {"profiles_dir": tmp_path}},
    )
    from image_triage.core.errors import UsageError

    with pytest.raises(UsageError):
        load_profile(settings, "does-not-exist")


def test_event_quotas_respect_sizes_and_rule() -> None:
    sizes = {1: 10, 2: 4, 3: 1}
    quotas = event_quotas(sizes, 5, "sainte_lague")
    assert sum(quotas.values()) == 5
    assert all(quotas[event] <= sizes[event] for event in sizes)
    assert quotas[3] == 1
    equal = event_quotas(sizes, 3, "equal")
    assert sum(equal.values()) == 3
    assert all(value <= sizes[event] for event, value in equal.items())


def test_selection_respects_event_day_and_cluster_caps() -> None:
    settings = load_settings(None)
    profile = load_profile(
        settings,
        overrides={
            "top_n": 6,
            "max_per_day": 2,
            "max_per_cluster": 1,
            "event_quota": "equal",
        },
    )
    photos = []
    photo_id = 1
    for day in range(3):
        for index in range(3):
            photo = _photo(
                f"d{day}-{index}.jpg",
                score=0.9 - index * 0.1,
                group=day * 3 + index + 1,
                event=1,
                taken=T0 + timedelta(days=day, minutes=index),
            )
            photo.id = photo_id
            photo_id += 1
            photos.append(photo)
    selected = select_photos(photos, profile)
    assert len(selected) == 6
    assert len({item.photo.group_id for item in selected}) == 6
    day_counts: dict[str, int] = {}
    for item in selected:
        day = item.photo.taken.date().isoformat()
        day_counts[day] = day_counts.get(day, 0) + 1
    assert all(count <= 2 for count in day_counts.values())
    assert select_photos(photos, profile) == selected


def test_selection_is_deterministic_and_avoids_duplicates() -> None:
    settings = load_settings(None)
    profile = load_profile(settings, overrides={"top_n": 2, "diversity": 0.8})
    photos = [
        _photo("a.jpg", score=0.9, group=1, event=1, taken=T0, embedding=[1.0, 0.0]),
        _photo("b.jpg", score=0.89, group=2, event=1, taken=T0, embedding=[0.99, 0.1]),
        _photo("c.jpg", score=0.6, group=3, event=1, taken=T0, embedding=[0.0, 1.0]),
    ]
    for index, photo in enumerate(photos, start=1):
        photo.id = index
    first = select_photos(photos, profile)
    second = select_photos(photos, profile)
    assert [item.photo.path for item in first] == [item.photo.path for item in second]
    assert first[1].photo.path == "c.jpg"


def _repository_with_photos(tmp_path: Path) -> Repository:
    repository = Repository.open(tmp_path / "state.db")
    for index in range(3):
        photo = _photo(
            f"p{index}.jpg",
            score=0.5 + index / 10,
            group=None,
            event=None,
            taken=T0 + timedelta(minutes=index),
        )
        photo.id = repository.upsert_photo(photo)
    return repository


def test_report_validates_against_schema_and_omits_gps(tmp_path: Path) -> None:
    repository = _repository_with_photos(tmp_path)
    try:
        photos = repository.all_photos()
        photos[0].gps_lat, photos[0].gps_lon = 50.0, 8.0
        run = Run("run-1", "run", T0, status=RunStatus.COMPLETED, counts={"photos": 3})
        settings = load_settings(None, {"input": {"root": tmp_path}})
        report = build_report(photos, photos[:1], settings, run)
        schema = json.loads(
            (
                Path(__file__).parents[1] / "src/image_triage/report/schema/report.schema.json"
            ).read_text()
        )
        validate(report, schema)
        assert "gps" not in report["photos"][0]
        report_with_gps = build_report(photos, photos[:1], settings, run, include_gps=True)
        assert report_with_gps["photos"][0]["gps"] == {"lat": 50.0, "lon": 8.0}
    finally:
        repository.close()


def test_csv_escapes_commas_quotes_and_newlines(tmp_path: Path) -> None:
    photo = _photo('a,"b"\nc.jpg', score=0.5, group=1, event=1, taken=T0)
    path = write_csv([photo], tmp_path / "out.csv")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["path"] == 'a,"b"\nc.jpg'
    assert rows[0]["score"] == "0.5"


def test_full_pipeline_writes_artifacts_and_is_deterministic(
    photo_dir: Path, tmp_path: Path
) -> None:
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "state.db"},
            "models": {"enabled": False},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        first = run_pipeline(settings, repository, output=tmp_path / "out1", top_n=2)
        first_report = (tmp_path / "out1" / "report.json").read_bytes()
        second = run_pipeline(settings, repository, output=tmp_path / "out2", top_n=2)
        second_report = (tmp_path / "out2" / "report.json").read_bytes()
    finally:
        repository.close()

    assert len(first.selected) == 2
    assert first.report_path is not None and first.report_path.is_file()
    assert first.csv_path is not None and first.csv_path.is_file()
    assert len(first.preview_paths) == 2
    assert len(first.export_paths) == 2
    assert first_report == second_report
    assert first.run_id == second.run_id

    exported = sorted(
        path.relative_to(tmp_path / "out1" / "originals").as_posix()
        for path in (tmp_path / "out1" / "originals").rglob("*.jpg")
    )
    expected = sorted(Path(item.photo.path).name for item in first.selected)
    assert exported == expected
    for photo in photo_dir.rglob("*.jpg"):
        assert photo.is_file()


def test_run_and_apply_cli(photo_dir: Path, tmp_path: Path) -> None:
    config = tmp_path / "image-triage.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "input": {"root": str(photo_dir)},
                "models": {"enabled": False},
            }
        )
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--json",
            "--top-n",
            "2",
            "--output",
            str(tmp_path / "out"),
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["selected"] == 2

    plan_file = tmp_path / "plan.json"
    planned = runner.invoke(
        app,
        ["plan", "--output", str(plan_file), "--top-n", "2", "--json", "--config", str(config)],
    )
    assert planned.exit_code == 0, planned.output
    applied = runner.invoke(
        app,
        [
            "apply",
            "--plan",
            str(plan_file),
            "--output",
            str(tmp_path / "applied"),
            "--json",
            "--config",
            str(config),
        ],
    )
    assert applied.exit_code == 0, applied.output
    assert len(list((tmp_path / "applied").rglob("*.jpg"))) == 2
