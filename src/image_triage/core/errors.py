"""Stable exit codes and CLI exceptions for the agent interface."""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    """Documented process exit codes."""

    OK = 0
    USAGE = 2
    INPUT = 3
    MODEL = 4
    PARTIAL = 5
    INTERNAL = 6


class TriageError(Exception):
    """Error that maps to a stable exit code and optional JSON details."""

    def __init__(
        self,
        message: str,
        exit_code: ExitCode = ExitCode.INTERNAL,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Return the stable error JSON document."""
        return {
            "error": {
                "type": type(self).__name__,
                "message": self.message,
                "exit_code": int(self.exit_code),
                "details": self.details,
            }
        }


class UsageError(TriageError):
    """Invalid arguments or configuration."""

    def __init__(self, message: str, **details: Any):
        super().__init__(message, ExitCode.USAGE, details=details)


class InputError(TriageError):
    """The input library is missing, empty or unreadable."""

    def __init__(self, message: str, **details: Any):
        super().__init__(message, ExitCode.INPUT, details=details)


class ModelError(TriageError):
    """A model file is missing, invalid or uses an unsupported provider."""

    def __init__(self, message: str, **details: Any):
        super().__init__(message, ExitCode.MODEL, details=details)


class PartialFailure(TriageError):
    """Analysis completed with per-file errors while --strict was requested."""

    def __init__(self, message: str, **details: Any):
        super().__init__(message, ExitCode.PARTIAL, details=details)
