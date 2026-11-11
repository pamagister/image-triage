"""Selection profiles loaded from YAML with CLI overrides."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from image_triage.core.errors import UsageError
from image_triage.core.settings import Settings

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "best200",
    "top_n": 200,
    "diversity": 0.5,
    "max_per_group": 1,
    "max_per_day": 5,
    "max_per_cluster": 3,
    "event_quota": "sainte_lague",
}


@dataclass(slots=True)
class SelectionProfile:
    """Validated selection settings."""

    name: str = "best200"
    top_n: int = 200
    diversity: float = 0.5
    max_per_group: int = 1
    max_per_day: int = 5
    max_per_cluster: int = 3
    event_quota: str = "sainte_lague"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
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


def _candidate_paths(settings: Settings, profile: str) -> list[Path]:
    names = [profile]
    if not profile.endswith((".yaml", ".yml")):
        names.append(profile + ".yaml")
    paths = []
    for name in names:
        paths.append(settings.selection.profiles_dir / name)
        paths.append(Path("profiles") / name)
        paths.append(Path(name))
    return paths


def load_profile(
    settings: Settings,
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> SelectionProfile:
    """Load a profile by name or path and apply CLI overrides.

    Missing ``best200`` falls back to built-in defaults; any other missing profile is
    a usage error. Explicit overrides always win.
    """
    name = profile or settings.selection.profile
    values = dict(DEFAULT_PROFILE)
    values["name"] = name
    values.update(
        {
            "top_n": settings.selection.top_n,
            "diversity": settings.selection.diversity,
            "max_per_group": settings.selection.max_per_group,
            "max_per_day": settings.selection.max_per_day,
            "max_per_cluster": settings.selection.max_per_cluster,
            "event_quota": settings.selection.event_quota,
        }
    )
    path = next(
        (candidate for candidate in _candidate_paths(settings, name) if candidate.is_file()), None
    )
    if path is not None:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise UsageError(f"invalid profile YAML: {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise UsageError(f"profile must be a mapping: {path}")
        unknown = set(loaded) - set(DEFAULT_PROFILE)
        if unknown:
            raise UsageError(f"unknown profile keys: {sorted(unknown)}", path=str(path))
        values.update(loaded)
        values["name"] = str(loaded.get("name", name))
    elif name not in {"best200", "default"}:
        raise UsageError(f"selection profile not found: {name}")

    values.update(overrides or {})
    result = SelectionProfile(**values)
    result.validate()
    return result
