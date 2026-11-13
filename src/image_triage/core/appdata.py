"""Platform-specific application directories for configuration, data and cache.

The central database lives under the user's data directory, independent of any photo
library. Environment overrides keep tests and portable installs isolated from the real
home directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "image-triage"
CONFIG_ENV = "IMAGE_TRIAGE_CONFIG_DIR"
DATA_ENV = "IMAGE_TRIAGE_DATA_DIR"
CACHE_ENV = "IMAGE_TRIAGE_CACHE_DIR"

#: File name of the central YAML configuration.
CONFIG_FILE_NAME = "config.yaml"
#: File name of the central SQLite database.
DATABASE_FILE_NAME = "triage.db"


def _env_dir(name: str) -> Path | None:
    """Return an explicitly configured directory, or ``None``."""
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def _windows_base(env_name: str, fallback: Path) -> Path:
    value = os.environ.get(env_name)
    return Path(value) if value else fallback


def config_dir() -> Path:
    """Directory holding the central configuration file."""
    override = _env_dir(CONFIG_ENV)
    if override is not None:
        return override
    if sys.platform.startswith("win"):
        base = _windows_base("APPDATA", Path.home() / "AppData" / "Roaming")
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_NAME


def data_dir() -> Path:
    """Directory holding the central database and default exports."""
    override = _env_dir(DATA_ENV)
    if override is not None:
        return override
    if sys.platform.startswith("win"):
        base = _windows_base("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def cache_dir() -> Path:
    """Directory for derived previews and GUI run artifacts."""
    override = _env_dir(CACHE_ENV)
    if override is not None:
        return override
    if sys.platform.startswith("win"):
        base = _windows_base("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return base / APP_NAME / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / APP_NAME


def config_file() -> Path:
    """Absolute path of the central YAML configuration."""
    return config_dir() / CONFIG_FILE_NAME


def database_file() -> Path:
    """Absolute path of the central SQLite database."""
    return data_dir() / DATABASE_FILE_NAME


def cache_subdir(name: str) -> Path:
    """Return a named cache subdirectory, for example ``previews``."""
    return cache_dir() / name


def default_export_root() -> Path:
    """Root directory for timestamped exports."""
    return data_dir() / "exports"


def ensure_directories() -> None:
    """Create the central directories when they do not exist yet."""
    for path in (config_dir(), data_dir(), cache_dir()):
        path.mkdir(parents=True, exist_ok=True)
