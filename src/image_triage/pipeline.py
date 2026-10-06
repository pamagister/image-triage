"""Scan -> analysis (+ objects) -> similarity groups -> scoring -> selection -> XMP -> export."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from logging import Logger
from pathlib import Path

import numpy as np
from config_cli_gui.config import ConfigManager
from PIL import Image, ImageOps

from image_triage import metadata
from image_triage.export import export_photos
from image_triage.metrics import exposure, sharpness
from image_triage.models import DOWNLOAD_HINT, ObjectDetector
from image_triage.scan import Photo, capture_time, find_images, find_raw_companion
from image_triage.scoring import rate_photos, score_photos
from image_triage.selection import select_top
from image_triage.similarity import file_digest, group_similar, perceptual_hash

PREVIEW_SIZE = 1024


def analyze_photo(path: Path, detector: ObjectDetector | None = None) -> Photo:
    with Image.open(path) as image:
        taken = capture_time(image, path)
        # JPEG draft mode decodes at reduced size, which is much faster for large files.
        image.draft("RGB", (PREVIEW_SIZE, PREVIEW_SIZE))
        preview = ImageOps.exif_transpose(image).convert("RGB")
    preview.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE))
    gray = np.asarray(preview.convert("L"))
    objects, embedding = detector.detect(preview) if detector else ([], None)
    return Photo(
        path=path,
        taken=taken,
        sharpness=sharpness(gray),
        exposure=exposure(gray),
        phash=perceptual_hash(preview),
        digest=file_digest(path),
        raw=find_raw_companion(path),
        objects=objects,
        embedding=embedding,
    )


def run(
    config: ConfigManager,
    logger: Logger,
    progress: Callable[[int, int], None] | None = None,
) -> list[Photo]:
    """Run the full selection and return all analyzed photos."""
    general, selection = config.general, config.selection
    similarity, scoring, meta = config.similarity, config.scoring, config.metadata
    models = config.models
    input_root = Path(general.input.value)
    output_root = Path(general.output.value)
    dry_run = general.dry_run.value

    if not input_root.is_dir():
        raise FileNotFoundError(f"Input folder not found: {input_root}")

    exiftool = None
    write_keywords = meta.write_keywords.value and models.enabled.value
    if (meta.write_xmp_rating.value or write_keywords) and not dry_run:
        exiftool = metadata.find_exiftool(meta.exiftool_path.value)
        if not exiftool:
            raise FileNotFoundError(f"ExifTool not found. {metadata.INSTALL_HINT}")

    detector = None
    if models.enabled.value:
        model_path = Path(models.object_detector.value)
        if not model_path.is_file():
            raise FileNotFoundError(f"Object model not found: {model_path}. {DOWNLOAD_HINT}")
        detector = ObjectDetector(model_path, models.confidence.value)

    paths = find_images(input_root, exclude=output_root)
    logger.info(f"Found {len(paths)} images in {input_root}")
    if not paths:
        return []

    photos: list[Photo] = []
    with ThreadPoolExecutor() as pool:
        futures = {path: pool.submit(analyze_photo, path, detector) for path in paths}
        for done, (path, future) in enumerate(futures.items(), start=1):
            try:
                photos.append(future.result())
            except Exception as e:
                logger.warning(f"Skipping {path}: {e}")
            if progress:
                progress(done, len(paths))

    groups = group_similar(
        [p.taken for p in photos],
        [p.phash for p in photos],
        [p.digest for p in photos],
        max_distance=similarity.max_hash_distance.value,
        max_time_gap_s=similarity.max_time_gap_s.value,
        embeddings=[p.embedding for p in photos],
        min_embedding_similarity=similarity.min_embedding_similarity.value,
    )
    for photo, group in zip(photos, groups):
        photo.group = group

    score_photos(
        photos,
        sharpness_weight=scoring.sharpness_weight.value,
        exposure_weight=scoring.exposure_weight.value,
        sharpness_reference=scoring.sharpness_reference.value,
        object_weight=scoring.object_weight.value if detector else 0.0,
        subject_classes={c.strip() for c in scoring.subject_classes.value.split(",")},
    )
    rate_photos(
        photos,
        blur_threshold=scoring.blur_threshold.value,
        max_per_group=selection.max_per_group.value,
        min_score_5=scoring.min_score_5.value,
        min_score_4=scoring.min_score_4.value,
    )

    top_n = selection.top_n.value
    if top_n > 0:
        selected = select_top(photos, top_n, selection.diversity.value)
        criterion = f"top {top_n} (best per motif, spread over folders)"
    else:
        selected = [p for p in photos if p.rating >= selection.min_rating.value]
        criterion = f"rated >= {selection.min_rating.value} stars"
    for photo in selected:
        photo.selected = True

    photos.sort(key=lambda p: (p.taken, p.path))
    for p in photos:
        objects = ",".join(sorted({d.label for d in p.objects}))
        logger.info(
            f"{'x' if p.selected else ' '} {'*' * p.rating:<5} group {p.group:>4}  "
            f"sharp {p.sharpness:7.1f}  exp {p.exposure:.2f}  score {p.score:.2f}  "
            f"{p.path.relative_to(input_root)}  {objects}"
        )
    logger.info(
        f"{len(photos)} photos in {len(set(groups))} groups, {len(selected)} selected: {criterion}"
    )

    if dry_run:
        logger.info("Dry run: no metadata written, nothing exported")
        return photos

    if exiftool:
        metadata.write_metadata(
            photos,
            exiftool,
            meta.sidecar_for_raw.value,
            meta.write_xmp_rating.value,
            write_keywords,
            logger,
        )
    export_photos(selected, input_root, output_root, selection.export_mode.value, logger)
    return photos
