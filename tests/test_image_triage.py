import hashlib
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import imagehash
import numpy as np
import pytest
from PIL import Image

from image_triage import metadata, pipeline
from image_triage.config import ImageTriageConfig
from image_triage.metrics import exposure
from image_triage.models import DEFAULT_MODEL_PATH, Detection, ObjectDetector, download_model
from image_triage.scan import Photo, capture_time
from image_triage.scoring import rate_photos, score_photos, subject_score
from image_triage.selection import event_quotas, pick_diverse, select_top
from image_triage.similarity import group_similar

LOG = logging.getLogger("test")
T0 = datetime(2024, 1, 1)


def _hash(bits: list[int]) -> imagehash.ImageHash:
    arr = np.zeros(64, bool)
    arr[bits] = True
    return imagehash.ImageHash(arr.reshape(8, 8))


def test_group_similar_requires_close_time_and_hash():
    times = [T0, T0 + timedelta(seconds=2), T0 + timedelta(seconds=60), T0 + timedelta(seconds=61)]
    hashes = [_hash([]), _hash([1, 2]), _hash([]), _hash(list(range(30)))]
    groups = group_similar(times, hashes, ["a", "b", "c", "d"], max_distance=5, max_time_gap_s=10)
    # 0+1 similar and close; 2 similar hash but far in time; 3 close but different
    assert groups == [1, 1, 2, 3]


def test_group_similar_joins_exact_duplicates_regardless_of_time():
    times = [T0, T0 + timedelta(days=1)]
    hashes = [_hash([]), _hash(list(range(40)))]
    assert group_similar(times, hashes, ["same", "same"], max_distance=5, max_time_gap_s=10) == [
        1,
        1,
    ]


def test_group_similar_joins_close_shots_with_similar_embeddings():
    times = [T0, T0 + timedelta(seconds=2), T0 + timedelta(seconds=4)]
    hashes = [_hash([]), _hash(list(range(30))), _hash(list(range(30, 60)))]
    a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    groups = group_similar(
        times, hashes, ["a", "b", "c"], 5, 10, embeddings=[a, a, b], min_embedding_similarity=0.97
    )
    assert groups == [1, 1, 2]


def test_capture_time_from_file_name(tmp_path: Path):
    path = tmp_path / "IMG_20150502_071410.jpg"
    Image.new("RGB", (8, 8)).save(path)
    with Image.open(path) as image:
        assert capture_time(image, path) == datetime(2015, 5, 2, 7, 14, 10)


def _photo(name: str, sharpness: float, exposure: float, group: int, **kwargs) -> Photo:
    return Photo(Path(name), T0, sharpness, exposure, _hash([]), name, group=group, **kwargs)


def test_subject_score_prefers_large_confident_subjects():
    big = Detection("person", 0.9, (0.2, 0.2, 0.6, 0.8))
    tiny = Detection("person", 0.9, (0.5, 0.5, 0.51, 0.52))
    chair = Detection("chair", 0.9, (0.0, 0.0, 1.0, 1.0))
    subjects = {"person"}
    assert subject_score(_photo("a", 1, 1, 1, objects=[big]), subjects) == pytest.approx(0.9)
    assert subject_score(_photo("b", 1, 1, 1, objects=[tiny]), subjects) < 0.01
    assert subject_score(_photo("c", 1, 1, 1, objects=[chair]), subjects) == 0.0


def test_ratings():
    photos = [
        _photo("best.jpg", 300, 1.0, 1),
        _photo("second.jpg", 200, 1.0, 1),
        _photo("blurry.jpg", 10, 1.0, 1),
        _photo("single_ok.jpg", 100, 0.8, 2),
        _photo("single_weak.jpg", 40, 0.5, 3),
        _photo("only_blurry.jpg", 5, 1.0, 4),
    ]
    score_photos(photos, sharpness_weight=0.6, exposure_weight=0.2, sharpness_reference=250)
    rate_photos(photos, blur_threshold=30, max_per_group=1, min_score_5=0.75, min_score_4=0.45)
    assert {p.path.name: p.rating for p in photos} == {
        "best.jpg": 5,
        "second.jpg": 2,
        "blurry.jpg": 1,
        "single_ok.jpg": 4,
        "single_weak.jpg": 3,
        "only_blurry.jpg": 1,
    }


def test_event_quotas_proportional_with_minimum_one():
    quotas = event_quotas({Path("holiday"): 30, Path("party"): 10, Path("walk"): 1}, 10)
    assert quotas[Path("walk")] == 1
    assert sum(quotas.values()) == 10
    assert quotas[Path("holiday")] > quotas[Path("party")] >= 1


def test_event_quotas_more_events_than_places():
    quotas = event_quotas({Path("a"): 1, Path("b"): 5, Path("c"): 2}, 2)
    assert quotas == {Path("a"): 0, Path("b"): 1, Path("c"): 1}


def _candidate(name: str, score: float, embedding: list[float], folder: str = "x") -> Photo:
    photo = _photo(f"{folder}/{name}", 100, 1, 0, embedding=np.array(embedding))
    photo.score, photo.best_in_group = score, True
    return photo


def test_pick_diverse_skips_similar_content():
    cat = _candidate("cat.jpg", 0.9, [1.0, 0.0, 0.0])
    cat_again = _candidate("cat_again.jpg", 0.85, [0.99, 0.1, 0.0])
    car = _candidate("car.jpg", 0.6, [0.0, 0.0, 1.0])
    photos = [cat, cat_again, car]
    vectors = {id(p): p.embedding / np.linalg.norm(p.embedding) for p in photos}
    assert pick_diverse(photos, 2, 0.5, vectors) == [cat, car]
    assert pick_diverse(photos, 2, 0.0, vectors) == [cat, cat_again]


def test_select_top_spreads_over_folders():
    photos = [_candidate(f"{i}.jpg", 0.9, [1.0, i], "party") for i in range(5)]
    photos += [_candidate("view.jpg", 0.3, [0.0, 1.0], "ski")]
    photos += [_photo("party/not_best.jpg", 100, 1, 0)]
    selected = select_top(photos, 3, 0.5)
    assert len(selected) == 3
    assert any(p.path.name == "view.jpg" for p in selected)
    assert all(p.best_in_group for p in selected)


def test_exposure_penalizes_clipping():
    mid = np.full((100, 100), 120, np.uint8)
    white = np.full((100, 100), 255, np.uint8)
    assert exposure(mid) == 1.0
    assert exposure(white) == 0.0


def _config(photo_dir: Path, output: Path, **overrides) -> ImageTriageConfig:
    overrides = {
        "metadata__write_xmp_rating": False,
        "metadata__write_keywords": False,
        "models__enabled": False,
        **overrides,
    }
    return ImageTriageConfig(general__input=photo_dir, general__output=output, **overrides)


def test_pipeline_selects_best_of_burst_and_exports(photo_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    # Synthetic scenes have less fine detail than real photos.
    config = _config(
        photo_dir, out, scoring__sharpness_reference=50.0, scoring__blur_threshold=15.0
    )
    photos = pipeline.run(config, LOG)
    by_name = {p.path.name: p for p in photos}

    burst = [by_name[n] for n in ("burst_sharp.jpg", "burst_soft.jpg", "burst_blurry.jpg")]
    assert len({p.group for p in burst}) == 1
    assert by_name["other.jpg"].group != burst[0].group
    assert by_name["burst_sharp.jpg"].best_in_group
    assert by_name["burst_sharp.jpg"].rating >= 4
    assert by_name["burst_soft.jpg"].rating == 2
    assert by_name["burst_blurry.jpg"].rating == 1

    exported = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.jpg"))
    expected = sorted(p.path.relative_to(photo_dir).as_posix() for p in photos if p.rating >= 4)
    assert exported == expected
    assert "burst_sharp.jpg" in exported


def test_dry_run_writes_nothing(photo_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    pipeline.run(_config(photo_dir, out, general__dry_run=True), LOG)
    assert not out.exists()


def test_output_inside_input_is_not_rescanned(photo_dir: Path):
    out = photo_dir / "selected"
    pipeline.run(_config(photo_dir, out), LOG)
    photos = pipeline.run(_config(photo_dir, out), LOG)
    assert all(out not in p.path.parents for p in photos)


def test_missing_model_fails_early(photo_dir: Path, tmp_path: Path):
    config = _config(photo_dir, tmp_path / "out", models__enabled=True)
    config.models.object_detector.value = tmp_path / "missing.onnx"
    with pytest.raises(FileNotFoundError, match="Download model"):
        pipeline.run(config, LOG)


def test_download_model_verifies_checksum(tmp_path: Path):
    source = tmp_path / "source.onnx"
    source.write_bytes(b"model")
    target = tmp_path / "res" / "model.onnx"
    url = source.as_uri()
    with pytest.raises(ValueError, match="Checksum"):
        download_model(target, url=url, sha256="0" * 64)
    assert not target.exists()
    download_model(target, url=url, sha256=hashlib.sha256(b"model").hexdigest())
    assert target.read_bytes() == b"model"


def test_keyword_commands_avoid_duplicates():
    photo = _photo("a.jpg", 100, 1, 1, objects=[Detection("dog", 0.9, (0, 0, 1, 1))] * 2)
    photo.rating = 4
    assert metadata._commands([photo], False, True, True) == [
        ["-XMP-xmp:Rating=4", "-XMP-dc:Subject-=dog", "-XMP-dc:Subject+=dog", "a.jpg"]
    ]
    assert metadata._commands([photo], False, False, False) == []


def test_missing_exiftool_fails_early(photo_dir: Path, tmp_path: Path):
    config = _config(photo_dir, tmp_path / "out", metadata__write_xmp_rating=True)
    config.metadata.exiftool_path.value = "does-not-exist-exiftool"
    with pytest.raises(FileNotFoundError, match="ExifTool"):
        pipeline.run(config, LOG)


@pytest.mark.skipif(not metadata.find_exiftool("exiftool"), reason="ExifTool not installed")
def test_writes_xmp_rating(photo_dir: Path, tmp_path: Path):
    raw = photo_dir / "burst_sharp.CR2"
    raw.write_bytes((photo_dir / "burst_sharp.jpg").read_bytes())
    config = _config(photo_dir, tmp_path / "out", metadata__write_xmp_rating=True)
    photos = pipeline.run(config, LOG)

    exiftool = metadata.find_exiftool("exiftool")
    for photo in photos:
        written = subprocess.run(
            [exiftool, "-s3", "-XMP-xmp:Rating", str(photo.path)], capture_output=True, text=True
        ).stdout.strip()
        assert written == str(photo.rating)
    sidecar = subprocess.run(
        [exiftool, "-s3", "-XMP-xmp:Rating", str(photo_dir / "burst_sharp.xmp")],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert sidecar == str(next(p.rating for p in photos if p.path.name == "burst_sharp.jpg"))


@pytest.mark.skipif(not metadata.find_exiftool("exiftool"), reason="ExifTool not installed")
def test_writes_keywords_without_duplicates(photo_dir: Path):
    exiftool = metadata.find_exiftool("exiftool")
    path = photo_dir / "burst_sharp.jpg"
    subprocess.run([exiftool, "-overwrite_original", "-XMP-dc:Subject=holiday", str(path)])
    objects = [Detection("person", 0.9, (0, 0, 1, 1)), Detection("dog", 0.8, (0, 0, 1, 1))]
    photo = _photo(str(path), 100, 1, 1, objects=objects)
    photo.rating = 5
    for _ in range(2):
        metadata.write_metadata([photo], exiftool, False, True, True, LOG)
    read = [exiftool, "-s3", "-sep", ",", str(path)]
    keywords = subprocess.run([*read, "-XMP-dc:Subject"], capture_output=True, text=True)
    assert keywords.stdout.strip() == "holiday,dog,person"


needs_model = pytest.mark.skipif(not DEFAULT_MODEL_PATH.is_file(), reason="YOLO model missing")


@needs_model
def test_object_detector_returns_embedding():
    detector = ObjectDetector(DEFAULT_MODEL_PATH, 0.5)
    detections, embedding = detector.detect(Image.new("RGB", (900, 600), (120, 120, 120)))
    assert embedding.shape == (256,)
    assert np.linalg.norm(embedding) == pytest.approx(1.0)
    assert all(0 <= v <= 1 for d in detections for v in d.box)


@needs_model
def test_pipeline_top_n_with_model(photo_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    config = _config(
        photo_dir,
        out,
        models__enabled=True,
        selection__top_n=1,
        scoring__sharpness_reference=50.0,
        scoring__blur_threshold=15.0,
    )
    photos = pipeline.run(config, LOG)
    assert sum(p.selected for p in photos) == 1
    assert len(list(out.rglob("*.jpg"))) == 1
