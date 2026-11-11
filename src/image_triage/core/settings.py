"""Typed configuration loaded from defaults, YAML, environment and CLI overrides.

Precedence is: explicit CLI overrides > environment variables > YAML file > defaults.
Environment variables use the ``IMAGE_TRIAGE_`` prefix and ``__`` between nested fields,
for example ``IMAGE_TRIAGE_SCORING__SHARPNESS_WEIGHT=0.5``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from blake3 import blake3
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_NAME = "image-triage.yaml"
ENV_PREFIX = "IMAGE_TRIAGE_"


class AppSettings(BaseModel):
    """General application behavior."""

    log_level: str = Field("INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    max_workers: int | None = Field(None, ge=1)
    strict: bool = False


class InputSettings(BaseModel):
    """Input library and state database location."""

    root: Path = Path(".")
    db_path: Path | None = None
    exclude: list[str] = Field(default_factory=lambda: [".image-triage", "selected", "previews"])
    follow_symlinks: bool = False


class AnalysisSettings(BaseModel):
    """Decode and inference settings."""

    preview_size: int = Field(1024, ge=64, le=4096)
    draft: bool = True
    batch_size: int = Field(4, ge=1)
    yolo_enabled: bool = True
    yolo_confidence: float = Field(0.5, ge=0.0, le=1.0)
    aesthetic_enabled: bool = True
    save_embeddings: bool = True


class ScoringSettings(BaseModel):
    """Versioned scoring formula and rating thresholds."""

    sharpness_weight: float = Field(0.45, ge=0.0)
    composition_weight: float = Field(0.25, ge=0.0)
    aesthetic_weight: float = Field(0.15, ge=0.0)
    subject_weight: float = Field(0.15, ge=0.0)
    blur_threshold: float = Field(0.15, ge=0.0, le=1.0)
    min_score_5: float = Field(0.75, ge=0.0, le=1.0)
    min_score_4: float = Field(0.45, ge=0.0, le=1.0)
    sharpness_percentile: float = Field(90.0, ge=50.0, le=100.0)
    subject_classes: list[str] = Field(
        default_factory=lambda: [
            "person",
            "bird",
            "cat",
            "dog",
            "horse",
            "sheep",
            "cow",
            "elephant",
            "bear",
            "zebra",
            "giraffe",
            "car",
            "bicycle",
            "motorcycle",
            "airplane",
            "boat",
        ]
    )

    @model_validator(mode="after")
    def _weights(self) -> ScoringSettings:
        total = (
            self.sharpness_weight
            + self.composition_weight
            + self.aesthetic_weight
            + self.subject_weight
        )
        if total <= 0:
            raise ValueError("at least one scoring weight must be greater than zero")
        return self


class SimilaritySettings(BaseModel):
    """Grouping and event thresholds."""

    max_hash_distance: int = Field(12, ge=0, le=64)
    max_time_gap_s: float = Field(10.0, ge=0.0)
    min_embedding_similarity: float = Field(0.97, ge=-1.0, le=1.0)
    event_gap_s: float = Field(4 * 3600, ge=0.0)
    gps_jump_km: float = Field(50.0, ge=0.0)


class SelectionSettings(BaseModel):
    """Selection quotas and diversity."""

    top_n: int = Field(200, ge=0)
    diversity: float = Field(0.5, ge=0.0, le=1.0)
    max_per_group: int = Field(1, ge=1)
    max_per_day: int = Field(5, ge=0)
    max_per_cluster: int = Field(3, ge=0)
    event_quota: str = Field("sainte_lague", pattern="^(sainte_lague|proportional|equal)$")
    profiles_dir: Path = Path("profiles")
    profile: str = Field("best200", min_length=1)


class ModelsSettings(BaseModel):
    """Model file locations and download behavior."""

    enabled: bool = True
    yolo_path: Path = Path("res/yolo/yolo26n.onnx")
    aesthetic_path: Path = Path("res/aesthetic/aesthetic.onnx")
    provider: str = "CPUExecutionProvider"
    auto_download: bool = False


class ReportSettings(BaseModel):
    """Report and preview generation."""

    include_gps: bool = False
    previews: bool = True
    preview_max_side: int = Field(1600, ge=64, le=4096)
    webp_quality: int = Field(80, ge=1, le=100)
    csv_columns: list[str] | None = None


class GuiSettings(BaseModel):
    """Local web GUI binding."""

    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    reload: bool = False


class Settings(BaseSettings):
    """Root settings document."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        extra="ignore",
        yaml_file=DEFAULT_CONFIG_NAME,
        yaml_file_encoding="utf-8",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    input: InputSettings = Field(default_factory=InputSettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    similarity: SimilaritySettings = Field(default_factory=SimilaritySettings)
    selection: SelectionSettings = Field(default_factory=SelectionSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
    gui: GuiSettings = Field(default_factory=GuiSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Insert the YAML source between environment variables and defaults."""
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @property
    def database_path(self) -> Path:
        """Absolute path of the SQLite state database."""
        configured = self.input.db_path
        if configured is not None:
            return configured.expanduser().resolve()
        return (self.input.root / ".image-triage" / "triage.db").expanduser().resolve()

    def fingerprint(self) -> str:
        """Stable hash of the effective configuration, used for reproducibility."""
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return blake3(encoded).hexdigest()

    def model_hashes(self) -> dict[str, str]:
        """SHA256 of configured model files, when they exist."""
        import hashlib

        hashes: dict[str, str] = {}
        for name, path in (
            ("yolo", self.models.yolo_path),
            ("aesthetic", self.models.aesthetic_path),
        ):
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(chunk)
                hashes[name] = digest.hexdigest()
        return hashes


def load_settings(
    config_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Settings:
    """Load settings with documented precedence.

    Args:
        config_path: YAML file to read. Defaults to ``image-triage.yaml`` in the CWD.
        overrides: Nested CLI overrides (highest priority).
        **kwargs: Additional explicit values, merged with ``overrides``.

    Returns:
        A validated :class:`Settings` instance.
    """
    yaml_file = Path(config_path) if config_path is not None else Path(DEFAULT_CONFIG_NAME)
    merged = dict(overrides or {})
    merged.update(kwargs)

    class ConfiguredSettings(Settings):
        model_config = SettingsConfigDict(
            env_prefix=ENV_PREFIX,
            env_nested_delimiter="__",
            extra="ignore",
            yaml_file=str(yaml_file),
            yaml_file_encoding="utf-8",
        )

    return ConfiguredSettings(**merged)
