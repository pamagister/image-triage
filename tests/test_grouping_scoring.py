"""Phase 3 tests: similarity grouping, event detection, scoring and ratings."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import imagehash
import numpy as np
import yaml
from typer.testing import CliRunner

from image_triage.cli.app import app
from image_triage.core.models import BlurKind, Metrics, Photo
from image_triage.core.settings import load_settings
from image_triage.grouping.events import detect_events
from image_triage.grouping.similarity import group_photos
from image_triage.scoring.score import rate_photos, score_photo

T0 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def _hash(bits: list[int]) -> str:
    array = np.zeros(64, bool)
    array[bits] = True
    return str(imagehash.ImageHash(array.reshape(8, 8)))


def _photo(
    name: str,
    *,
    taken: datetime = T0,
    phash: str = "",
    digest: str = "",
    embedding: list[float] | None = None,
    gps: tuple[float, float] | None = None,
    **metrics: float,
) -> Photo:
    return Photo(
        path=name,
        digest=digest or name,
        phash=phash,
        taken=taken,
        gps_lat=gps[0] if gps else None,
        gps_lon=gps[1] if gps else None,
        embedding=embedding,
        metrics=Metrics(**metrics),
    )


def test_grouping_joins_duplicates_and_close_series() -> None:
    settings = load_settings(None)
    photos = [
        _photo("a.jpg", taken=T0, phash=_hash([]), digest="same"),
        _photo("b.jpg", taken=T0 + timedelta(days=2), phash=_hash(list(range(40))), digest="same"),
        _photo("c.jpg", taken=T0 + timedelta(seconds=2), phash=_hash([1, 2])),
        _photo("d.jpg", taken=T0 + timedelta(minutes=30), phash=_hash(list(range(30)))),
    ]
    groups = group_photos(photos, settings.similarity)
    assert groups[0] == groups[1]
    assert groups[0] == groups[2]
    assert groups[3] != groups[0]


def test_grouping_uses_embedding_similarity() -> None:
    settings = load_settings(None)
    photos = [
        _photo("a.jpg", taken=T0, phash=_hash([]), embedding=[1.0, 0.0]),
        _photo(
            "b.jpg",
            taken=T0 + timedelta(seconds=1),
            phash=_hash(list(range(30))),
            embedding=[1.0, 0.0],
        ),
        _photo(
            "c.jpg",
            taken=T0 + timedelta(seconds=2),
            phash=_hash(list(range(30, 60))),
            embedding=[0.0, 1.0],
        ),
    ]
    assert group_photos(photos, settings.similarity) == [1, 1, 2]


def test_events_split_on_time_day_and_gps() -> None:
    photos = [
        _photo("a.jpg", taken=T0, gps=(50.0, 8.0)),
        _photo("b.jpg", taken=T0 + timedelta(minutes=5), gps=(50.001, 8.0)),
        _photo("c.jpg", taken=T0 + timedelta(hours=6), gps=(50.0, 8.0)),
        _photo("d.jpg", taken=T0 + timedelta(hours=7), gps=(51.0, 8.0)),
    ]
    for index, photo in enumerate(photos, start=1):
        photo.id = index
    events, assignments = detect_events(photos, gap_s=4 * 3600, gps_jump_km=50)
    assert len(events) == 3
    assert [event.photo_count for event in events] == [2, 1, 1]
    assert events[1].source == "time"
    assert events[2].source == "gps"
    assert len(assignments) == 4


def test_score_is_deterministic_and_blurred_photos_are_gated() -> None:
    settings = load_settings(None)
    sharp = _photo(
        "sharp.jpg",
        sharpness=0.8,
        composition=0.7,
        aesthetic=0.6,
        subject_score=0.5,
        subject_rarity=0.5,
    )
    blurry = _photo(
        "blurry.jpg",
        sharpness=0.05,
        blur_kind=BlurKind.MOTION,
        blur_confidence=0.9,
        composition=0.7,
        aesthetic=0.6,
    )
    first = score_photo(sharp, settings)
    second = score_photo(sharp, settings)
    assert first.score == second.score
    assert 0.0 <= first.score <= 1.0
    assert score_photo(blurry, settings).blurry is True
    assert score_photo(blurry, settings).score < first.score


def test_rating_rules() -> None:
    settings = load_settings(None)
    photos = [
        _photo("best.jpg", sharpness=0.95, composition=0.9, aesthetic=0.9),
        _photo("second.jpg", sharpness=0.8, composition=0.6, aesthetic=0.6),
        _photo("blurry.jpg", sharpness=0.01, blur_kind=BlurKind.DEFOCUS, blur_confidence=0.9),
        _photo("weak.jpg", sharpness=0.3, composition=0.2, aesthetic=0.2),
    ]
    for photo in photos:
        photo.group_id = 1
    rate_photos(photos, settings)
    by_name = {photo.path: photo.rating for photo in photos}
    assert by_name["best.jpg"] == 5
    assert by_name["second.jpg"] == 2
    assert by_name["blurry.jpg"] == 1
    assert by_name["weak.jpg"] == 2


def test_score_cli_after_analyze(photo_dir: Path, tmp_path: Path) -> None:
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
    analyzed = runner.invoke(app, ["analyze", "--json", "--config", str(config)])
    assert analyzed.exit_code == 0, analyzed.output
    result = runner.invoke(app, ["score", "--json", "--config", str(config)])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["count"] == 4
    assert summary["groups"] >= 1
    assert summary["events"] >= 1
    assert len(summary["top"]) == 4
