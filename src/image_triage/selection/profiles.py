"""Selection profiles loaded from YAML with CLI overrides."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from image_triage.core.errors import UsageError
from image_triage.core.settings import Settings

SELECTIONS_FILE_NAME = "selections.yaml"
PACKAGE_PROFILE_DIR = Path(__file__).parent.parent / "profiles"

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "best50",
    "top_n": 50,
    "diversity": 0.5,
    "max_per_group": 1,
    "max_per_day": 5,
    "max_per_cluster": 3,
    "event_quota": "sainte_lague",
}

_PROFILE_KEYS = {
    "name",
    "top_n",
    "diversity",
    "max_per_group",
    "max_per_day",
    "max_per_cluster",
    "event_quota",
}


@dataclass(slots=True)
class SelectionProfile:
    """Validated selection settings."""

    name: str = "best50"
    top_n: int = 50
    diversity: float = 0.5
    max_per_group: int = 1
    max_per_day: int = 5
    max_per_cluster: int = 3
    event_quota: str = "sainte_lague"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not self.name.strip():
            raise UsageError("profile name must not be empty")
        if self.top_n < 0:
            raise UsageError("top_n must be >= 0", top_n=self.top_n)
        if not 0.0 <= self.diversity <= 1.0:
            raise UsageError("diversity must be between 0 and 1", diversity=self.diversity)
        if self.max_per_group < 1:
            raise UsageError("max_per_group must be >= 1")
        if self.max_per_day < 0 or self.max_per_cluster < 0:
            raise UsageError("per-day and per-cluster caps must be >= 0")
        if self.event_quota not in {"sainte_lague", "proportional", "equal"}:
            raise UsageError(f"unknown event quota: {self.event_quota}")


def profiles_path(settings: Settings) -> Path:
    """Path of the editable central ``selections.yaml``.

    Relative ``selection.profiles_dir`` values are resolved against the central config
    directory so a GUI started outside the source tree still uses the same profiles.
    """
    configured = settings.selection.profiles_dir.expanduser()
    if configured.is_absolute():
        return configured / SELECTIONS_FILE_NAME
    return settings.config_path.parent / configured / SELECTIONS_FILE_NAME


def package_profiles_path() -> Path:
    """Path of the read-only profiles shipped inside the installed package."""
    return PACKAGE_PROFILE_DIR / SELECTIONS_FILE_NAME


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise UsageError(f"invalid profile YAML: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise UsageError(f"profile file must be a mapping: {path}")
    return loaded


def _default_profiles() -> list[dict[str, Any]]:
    """Read the packaged selection profiles."""
    path = package_profiles_path()
    if not path.is_file():
        raise UsageError(f"packaged selection profiles not found: {path}")
    loaded = _read_yaml(path)
    profiles = loaded.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise UsageError(f"packaged selection profiles must contain a non-empty list: {path}")
    return [dict(item) for item in profiles]


def _profile_from_mapping(values: dict[str, Any], *, path: Path) -> SelectionProfile:
    unknown = set(values) - _PROFILE_KEYS
    if unknown:
        raise UsageError(f"unknown profile keys: {sorted(unknown)}", path=str(path))
    if "name" not in values or not str(values["name"]).strip():
        raise UsageError("profile name must not be empty", path=str(path))
    result = SelectionProfile(**values)
    result.validate()
    return result


def ensure_profiles(settings: Settings) -> Path:
    """Seed the editable ``selections.yaml`` from the package defaults when missing."""
    target = profiles_path(settings)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    source = package_profiles_path()
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    temporary.replace(target)
    return target


def load_profiles(settings: Settings, *, create: bool = True) -> list[SelectionProfile]:
    """Load every selection profile from the central YAML file.

    ``create=False`` is used by read-only pages: if the editable file does not exist yet,
    the packaged defaults are returned without writing to the config directory.
    """
    path = ensure_profiles(settings) if create else profiles_path(settings)
    if not path.is_file():
        if create:
            raise UsageError(f"selection profiles not found: {path}")
        return [
            _profile_from_mapping(values, path=package_profiles_path())
            for values in _default_profiles()
        ]
    loaded = _read_yaml(path)
    profiles = loaded.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise UsageError(f"selection profiles must contain a non-empty list: {path}")
    result: list[SelectionProfile] = []
    names: set[str] = set()
    for values in profiles:
        if not isinstance(values, dict):
            raise UsageError(f"selection profile must be a mapping: {path}")
        profile = _profile_from_mapping(values, path=path)
        if profile.name in names:
            raise UsageError(f"duplicate selection profile name: {profile.name}", path=str(path))
        names.add(profile.name)
        result.append(profile)
    return result


def load_profile(
    settings: Settings,
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> SelectionProfile:
    """Load one profile by name and apply explicit overrides.

    Explicit overrides always win. The active profile in ``settings.selection.profile`` is
    used when no profile name is supplied.
    """
    name = profile or settings.selection.profile
    profiles = load_profiles(settings, create=False)
    by_name = {item.name: item for item in profiles}
    if name in by_name:
        selected = by_name[name]
    elif profile is None and profiles:
        # An old config may reference a removed profile; use the first configured profile.
        selected = profiles[0]
    else:
        raise UsageError(f"selection profile not found: {name}")
    values = selected.to_dict()
    values.update(overrides or {})
    result = _profile_from_mapping(values, path=package_profiles_path())
    result.name = selected.name
    return result


def profiles_yaml(profiles: list[SelectionProfile]) -> str:
    """Validate and serialize profiles without writing any files."""
    if not profiles:
        raise UsageError("at least one selection profile is required")
    names: set[str] = set()
    for profile in profiles:
        profile.validate()
        if profile.name in names:
            raise UsageError(f"duplicate selection profile name: {profile.name}")
        names.add(profile.name)
    return yaml.safe_dump(
        {"profiles": [profile.to_dict() for profile in profiles]},
        sort_keys=False,
        allow_unicode=True,
    )


def write_profiles(settings: Settings, profiles: list[SelectionProfile]) -> Path:
    """Validate and atomically write the central ``selections.yaml``."""
    serialized = profiles_yaml(profiles)
    path = profiles_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)
    return path
