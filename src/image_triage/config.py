"""All configuration parameters (single source for CLI, GUI and config file)."""

from pathlib import Path

from config_cli_gui.config import ConfigCategory, ConfigManager, ConfigParameter

from image_triage.export import EXPORT_MODES
from image_triage.models import DEFAULT_MODEL_PATH


class GeneralConfig(ConfigCategory):
    def get_category_name(self) -> str:
        return "general"

    input: ConfigParameter = ConfigParameter(
        name="input",
        value=Path("."),
        help="Folder with photos (searched recursively)",
        cli_arg="--input",
        is_cli=True,
    )
    output: ConfigParameter = ConfigParameter(
        name="output",
        value=Path("selected"),
        help="Folder the selected photos are exported to",
        cli_arg="--output",
        is_cli=True,
    )
    dry_run: ConfigParameter = ConfigParameter(
        name="dry_run",
        value=False,
        help="Only analyze and report, do not write metadata or export",
        cli_arg="--dry-run",
        is_cli=True,
    )


class SelectionConfig(ConfigCategory):
    def get_category_name(self) -> str:
        return "selection"

    top_n: ConfigParameter = ConfigParameter(
        name="top_n",
        value=0,
        help="Export the N most relevant photos: best of each motif, spread over all "
        "subfolders (0 = export by min_rating instead)",
        cli_arg="--top-n",
        is_cli=True,
    )
    min_rating: ConfigParameter = ConfigParameter(
        name="min_rating",
        value=4,
        choices=[1, 2, 3, 4, 5],
        help="Export photos with at least this many stars (if top_n is 0)",
        cli_arg="--min-rating",
        is_cli=True,
    )
    max_per_group: ConfigParameter = ConfigParameter(
        name="max_per_group",
        value=1,
        help="Number of best photos per similarity group that can get 3-5 stars",
        cli_arg="--max-per-group",
        is_cli=True,
    )
    export_mode: ConfigParameter = ConfigParameter(
        name="export_mode",
        value="copy",
        choices=EXPORT_MODES,
        help="How photos are placed in the output folder",
        cli_arg="--export-mode",
        is_cli=True,
    )
    diversity: ConfigParameter = ConfigParameter(
        name="diversity",
        value=0.5,
        help="Top N: penalty for photos whose content resembles already selected ones "
        "(0 = rank by score only)",
    )


class SimilarityConfig(ConfigCategory):
    def get_category_name(self) -> str:
        return "similarity"

    max_hash_distance: ConfigParameter = ConfigParameter(
        name="max_hash_distance",
        value=20,
        help="Max. differing pHash bits (of 64) for two photos to count as similar",
    )
    max_time_gap_s: ConfigParameter = ConfigParameter(
        name="max_time_gap_s",
        value=10.0,
        help="Max. seconds between two shots to be compared for similarity",
    )
    min_embedding_similarity: ConfigParameter = ConfigParameter(
        name="min_embedding_similarity",
        value=0.97,
        help="Shots taken close together also count as similar if their content embeddings "
        "(object model) have at least this cosine similarity",
    )


class ScoringConfig(ConfigCategory):
    def get_category_name(self) -> str:
        return "scoring"

    sharpness_weight: ConfigParameter = ConfigParameter(
        name="sharpness_weight",
        value=0.6,
        help="Weight of sharpness in the quality score",
    )
    exposure_weight: ConfigParameter = ConfigParameter(
        name="exposure_weight",
        value=0.2,
        help="Weight of exposure in the quality score",
    )
    object_weight: ConfigParameter = ConfigParameter(
        name="object_weight",
        value=0.2,
        help="Weight of a large, clearly detected subject in the score (object model)",
    )
    subject_classes: ConfigParameter = ConfigParameter(
        name="subject_classes",
        value="person,bird,cat,dog,horse,sheep,cow,elephant,bear,zebra,giraffe",
        help="Comma-separated object classes that count as subject",
    )
    sharpness_reference: ConfigParameter = ConfigParameter(
        name="sharpness_reference",
        value=250.0,
        help="Sharpness value (Laplacian variance) that counts as fully sharp",
    )
    blur_threshold: ConfigParameter = ConfigParameter(
        name="blur_threshold",
        value=30.0,
        help="Photos below this sharpness are rated as blurry (1 star)",
    )
    min_score_5: ConfigParameter = ConfigParameter(
        name="min_score_5",
        value=0.75,
        help="Min. score (0-1) of a group's best photo for 5 stars",
    )
    min_score_4: ConfigParameter = ConfigParameter(
        name="min_score_4",
        value=0.5,
        help="Min. score (0-1) of a group's best photo for 4 stars (else 3)",
    )


class ModelsConfig(ConfigCategory):
    def get_category_name(self) -> str:
        return "models"

    enabled: ConfigParameter = ConfigParameter(
        name="enabled",
        value=True,
        help="Detect objects (YOLO) for scoring, content diversity and keywords",
        cli_arg="--models-enabled",
        is_cli=True,
    )
    object_detector: ConfigParameter = ConfigParameter(
        name="object_detector",
        value=DEFAULT_MODEL_PATH,
        help="YOLO26 ONNX model file",
    )
    confidence: ConfigParameter = ConfigParameter(
        name="confidence",
        value=0.5,
        help="Min. confidence (0-1) of an object detection",
    )


class MetadataConfig(ConfigCategory):
    def get_category_name(self) -> str:
        return "metadata"

    write_xmp_rating: ConfigParameter = ConfigParameter(
        name="write_xmp_rating",
        value=True,
        help="Write the star rating as XMP Rating into the image files",
        cli_arg="--write-xmp-rating",
        is_cli=True,
    )
    write_keywords: ConfigParameter = ConfigParameter(
        name="write_keywords",
        value=True,
        help="Write detected objects as XMP keywords (dc:subject), existing keywords are kept",
        cli_arg="--write-keywords",
        is_cli=True,
    )
    sidecar_for_raw: ConfigParameter = ConfigParameter(
        name="sidecar_for_raw",
        value=True,
        help="Also write the rating to an .xmp sidecar of a RAW file with the same name",
    )
    exiftool_path: ConfigParameter = ConfigParameter(
        name="exiftool_path",
        value="exiftool",
        help="ExifTool executable (name on PATH or full path)",
    )


class ImageTriageConfig(ConfigManager):
    general: GeneralConfig
    selection: SelectionConfig
    similarity: SimilarityConfig
    scoring: ScoringConfig
    models: ModelsConfig
    metadata: MetadataConfig

    def __init__(self, config_file: str | None = None, **kwargs):
        categories = (
            GeneralConfig(),
            SelectionConfig(),
            SimilarityConfig(),
            ScoringConfig(),
            ModelsConfig(),
            MetadataConfig(),
        )
        super().__init__(categories, config_file, **kwargs)

    @staticmethod
    def get_app_name() -> str:
        return "image-triage"
