from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "application_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class QueueUnavailableError(AppError):
    status_code = 503
    code = "queue_unavailable"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
