from __future__ import annotations

import json
import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_context: ContextVar[dict[str, str] | None] = ContextVar("worker_log_context", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **(_context.get() or {}),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class ContextLogger(logging.LoggerAdapter[logging.Logger]):
    def process(self, msg: object, kwargs: MutableMapping[str, Any]) -> tuple[object, MutableMapping[str, Any]]:
        extra = kwargs.setdefault("extra", {})
        fields = dict(self.extra or {})
        fields.update(kwargs.pop("fields", {}))
        extra["fields"] = fields
        return msg, kwargs


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def bind_context(**values: str) -> None:
    current = dict(_context.get() or {})
    current.update(values)
    _context.set(current)


def clear_context() -> None:
    _context.set({})


def get_logger(name: str, **values: str) -> ContextLogger:
    return ContextLogger(logging.getLogger(name), values)
