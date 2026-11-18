"""Filter presets loaded from one central YAML file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from image_triage.core.errors import UsageError
from image_triage.core.settings import Settings

FILTERS_FILE_NAME = "filters.yaml"
PACKAGE_FILTERS_PATH = Path(__file__).parent.parent / "profiles" / FILTERS_FILE_NAME

#: Filter query keys a preset may set. This mirrors the library query parser.
FILTER_KEYS = {
    "q",
    "rating",
    "event_id",
    "group_id",
    "label",
    "blur",
    "flags",
    "camera_make",
    "camera_model",
    "status",
    "root",
    "folder",
    "date_from",
    "date_to",
    "min_score",
    "score_max",
    "sharpness_min",
    "sharpness_max",
    "bokeh_min",
    "bokeh_max",
    "blur_min",
    "blur_max",
    "composition_min",
    "composition_max",
    "aesthetic_min",
    "aesthetic_max",
    "subject_min",
    "subject_max",
    "exposure_min",
    "exposure_max",
    "group_size_min",
    "group_size_max",
    "hide_rejected",
}

_LIST_KEYS = {
    "rating",
    "event_id",
    "group_id",
    "label",
    "blur",
    "flags",
    "camera_make",
    "camera_model",
    "status",
    "root",
    "folder",
}
_INT_KEYS = {"event_id", "group_id", "group_size_min", "group_size_max"}
_FLOAT_KEYS = {
    "min_score",
    "score_max",
    "sharpness_min",
    "sharpness_max",
    "bokeh_min",
    "bokeh_max",
    "blur_min",
    "blur_max",
    "composition_min",
    "composition_max",
    "aesthetic_min",
    "aesthetic_max",
    "subject_min",
    "subject_max",
    "exposure_min",
    "exposure_max",
}
_BOOL_KEYS = {"hide_rejected"}


def _field_kind(key: str) -> str:
    if key in _LIST_KEYS:
        return "list"
    if key in _INT_KEYS:
        return "int"
    if key in _FLOAT_KEYS:
        return "float"
    if key in _BOOL_KEYS:
        return "bool"
    return "text"


#: Stable field order shared by the settings form and its parser.
FILTER_FIELDS = tuple(sorted(FILTER_KEYS))
FILTER_FIELD_KINDS = {key: _field_kind(key) for key in FILTER_FIELDS}


@dataclass(slots=True)
class FilterPreset:
    """One named set of library filter overrides."""

    name: str
    label: str
    overrides: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "overrides": self.overrides}


def filters_path(settings: Settings) -> Path:
    """Path of the editable central ``filters.yaml``.

    Relative paths are resolved against the central config directory so the GUI and CLI
    agree regardless of the current working directory.
    """
    configured = settings.selection.profiles_dir.expanduser()
    base = configured if configured.is_absolute() else settings.config_path.parent / configured
    return base / FILTERS_FILE_NAME


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise UsageError(f"invalid filter preset YAML: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise UsageError(f"filter preset file must be a mapping: {path}")
    return loaded


def _default_presets() -> list[dict[str, Any]]:
    loaded = _read_yaml(PACKAGE_FILTERS_PATH)
    presets = loaded.get("presets")
    if not isinstance(presets, list) or not presets:
        raise UsageError(
            f"packaged filter presets must contain a non-empty list: {PACKAGE_FILTERS_PATH}"
        )
    return [dict(item) for item in presets]


def _validate_overrides(overrides: Any, *, path: Path) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        raise UsageError("preset overrides must be a mapping", path=str(path))
    if not overrides:
        return {}
    unknown = set(overrides) - FILTER_KEYS
    if unknown:
        raise UsageError(f"unknown filter keys: {sorted(unknown)}", path=str(path))
    result: dict[str, Any] = {}
    for key, value in overrides.items():
        if key == "status" and value == ["all"]:
            continue
        if key in _LIST_KEYS:
            if not isinstance(value, list) or not value:
                raise UsageError(f"{key} must be a non-empty list", path=str(path))
            if key in _INT_KEYS:
                try:
                    result[key] = [int(item) for item in value]
                except (TypeError, ValueError) as exc:
                    raise UsageError(f"{key} must contain integers", path=str(path)) from exc
            elif key == "rating":
                try:
                    result[key] = [int(item) for item in value]
                except (TypeError, ValueError) as exc:
                    raise UsageError(f"{key} must contain integers", path=str(path)) from exc
            else:
                result[key] = [str(item) for item in value]
        elif key in _INT_KEYS:
            try:
                result[key] = int(value)
            except (TypeError, ValueError) as exc:
                raise UsageError(f"{key} must be an integer", path=str(path)) from exc
        elif key in _FLOAT_KEYS:
            try:
                result[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise UsageError(f"{key} must be a number", path=str(path)) from exc
        elif key == "hide_rejected":
            if not isinstance(value, bool):
                raise UsageError("hide_rejected must be a boolean", path=str(path))
            result[key] = value
        elif key in {"date_from", "date_to"}:
            result[key] = str(value)
        else:
            result[key] = value
    return result


def preset_from_mapping(values: dict[str, Any], *, path: Path) -> FilterPreset:
    """Validate one preset mapping."""
    unknown = set(values) - {"name", "label", "overrides"}
    if unknown:
        raise UsageError(f"unknown preset keys: {sorted(unknown)}", path=str(path))
    name = str(values.get("name", "")).strip()
    label = str(values.get("label", "")).strip()
    if not name:
        raise UsageError("preset name must not be empty", path=str(path))
    if not label:
        label = name
    overrides = _validate_overrides(values.get("overrides"), path=path)
    return FilterPreset(name=name, label=label, overrides=overrides)


def overrides_from_field_values(values: list[str], *, path: Path) -> dict[str, Any]:
    """Parse ``key=value`` form fields for one preset into validated overrides.

    Empty values are omitted so a newly added preset can be saved before its filters are
    filled in. List-valued fields use comma-separated values.
    """
    overrides: dict[str, Any] = {}
    for raw in values:
        key, separator, raw_value = raw.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        if key not in FILTER_KEYS:
            raise UsageError(f"unknown filter key: {key}", path=str(path))
        value = raw_value.strip()
        if value == "":
            continue
        kind = FILTER_FIELD_KINDS[key]
        if kind == "list":
            items = [item.strip() for item in value.split(",") if item.strip()]
            if key in _INT_KEYS or key == "rating":
                try:
                    overrides[key] = [int(item) for item in items]
                except ValueError as exc:
                    raise UsageError(f"{key} must contain integers", path=str(path)) from exc
            else:
                overrides[key] = items
        elif kind == "int":
            try:
                overrides[key] = int(value)
            except ValueError as exc:
                raise UsageError(f"{key} must be an integer", path=str(path)) from exc
        elif kind == "float":
            try:
                overrides[key] = float(value)
            except ValueError as exc:
                raise UsageError(f"{key} must be a number", path=str(path)) from exc
        elif kind == "bool":
            lowered = value.lower()
            if lowered not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                raise UsageError(f"{key} must be true or false", path=str(path))
            overrides[key] = lowered in {"true", "1", "yes", "on"}
        else:
            overrides[key] = value
    return _validate_overrides(overrides, path=path)


def load_presets(settings: Settings, *, create: bool = True) -> list[FilterPreset]:
    """Load every filter preset from the central YAML file.

    ``create=False`` is used by read-only pages: if the editable file does not exist yet,
    the packaged defaults are returned without writing to the config directory.
    """
    path = ensure_filters(settings) if create else filters_path(settings)
    if not path.is_file():
        if create:
            raise UsageError(f"filter presets not found: {path}")
        return [
            preset_from_mapping(values, path=PACKAGE_FILTERS_PATH) for values in _default_presets()
        ]
    loaded = _read_yaml(path)
    presets = loaded.get("presets")
    if not isinstance(presets, list) or not presets:
        raise UsageError(f"filter presets must contain a non-empty list: {path}")
    result: list[FilterPreset] = []
    names: set[str] = set()
    for values in presets:
        if not isinstance(values, dict):
            raise UsageError(f"filter preset must be a mapping: {path}")
        preset = preset_from_mapping(values, path=path)
        if preset.name in names:
            raise UsageError(f"duplicate filter preset name: {preset.name}", path=str(path))
        names.add(preset.name)
        result.append(preset)
    return result


def ensure_filters(settings: Settings) -> Path:
    """Seed the editable ``filters.yaml`` from the package defaults when missing."""
    target = filters_path(settings)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        PACKAGE_FILTERS_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def active_presets(settings: Settings) -> list[FilterPreset]:
    """Presets enabled in ``gui.filters.presets``, in configured order."""
    by_name = {preset.name: preset for preset in load_presets(settings, create=False)}
    return [by_name[name] for name in settings.gui.filters.presets if name in by_name]


def presets_yaml(presets: list[FilterPreset]) -> str:
    """Validate and serialize presets without writing any files."""
    if not presets:
        raise UsageError("at least one filter preset is required")
    names: set[str] = set()
    for preset in presets:
        if not preset.name.strip():
            raise UsageError("preset name must not be empty")
        if preset.name in names:
            raise UsageError(f"duplicate filter preset name: {preset.name}")
        names.add(preset.name)
        preset_from_mapping(preset.to_dict(), path=PACKAGE_FILTERS_PATH)
    return yaml.safe_dump(
        {"presets": [preset.to_dict() for preset in presets]},
        sort_keys=False,
        allow_unicode=True,
    )


def write_presets(settings: Settings, presets: list[FilterPreset]) -> Path:
    """Validate and atomically write the central ``filters.yaml``."""
    serialized = presets_yaml(presets)
    path = filters_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)
    return path
