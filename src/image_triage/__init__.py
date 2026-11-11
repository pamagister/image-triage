"""Local, deterministic photo triage."""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("image-triage")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0"

__all__ = ["__version__"]