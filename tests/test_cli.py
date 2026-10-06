import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from image_triage import metadata

ROOT = Path(__file__).parents[1]
SAMPLE_IMAGES = ROOT / "images" / "testimages_5"


def _copy_sample_images(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    shutil.copytree(SAMPLE_IMAGES, input_dir)
    return input_dir


def _run_cli(input_dir: Path, output_dir: Path, *options: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "image_triage",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--models-enabled",
            "false",
            "--write-keywords",
            "false",
            *options,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_cli_top_n_exports_four_sample_images(tmp_path: Path):
    input_dir = _copy_sample_images(tmp_path)
    output_dir = tmp_path / "selected"

    _run_cli(
        input_dir,
        output_dir,
        "--top-n",
        "4",
        "--write-xmp-rating",
        "false",
    )

    exported = list(output_dir.rglob("*.jpg"))
    assert len(exported) == 4
    assert all((input_dir / image.name).is_file() for image in exported)


@pytest.mark.skipif(not metadata.find_exiftool("exiftool"), reason="ExifTool not installed")
def test_cli_writes_ratings_to_copied_sample_images(tmp_path: Path):
    input_dir = _copy_sample_images(tmp_path)

    _run_cli(
        input_dir,
        tmp_path / "selected",
        "--top-n",
        "4",
        "--write-xmp-rating",
        "true",
    )

    exiftool = metadata.find_exiftool("exiftool")
    assert exiftool
    for image in input_dir.glob("*.jpg"):
        result = subprocess.run(
            [exiftool, "-s3", "-XMP-xmp:Rating", str(image)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() in {"1", "2", "3", "4", "5"}
