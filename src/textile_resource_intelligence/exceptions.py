"""Application-level exceptions raised by the service layer."""

from __future__ import annotations

from collections.abc import Iterable

from .domain.types import Issue


class ValidationFailed(Exception):
    """Input did not pass validation. ``issues`` holds the structured messages."""

    def __init__(self, issues: Iterable[Issue]) -> None:
        self.issues: tuple[Issue, ...] = tuple(issues)
        errors = [i.message for i in self.issues if i.is_error] or [i.message for i in self.issues]
        super().__init__(" ".join(errors) or "Validation failed.")


class RepositoryError(Exception):
    """A storage operation failed and was rolled back. The message is user-safe."""


class NotFound(Exception):
    """The requested record does not exist."""


class ImportFileError(Exception):
    """The uploaded file cannot be read as CSV. The message is user-safe."""


class DatabaseVersionError(Exception):
    """The database file has an unrecognised or newer schema version."""
