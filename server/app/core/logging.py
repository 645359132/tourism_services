"""Predictable application logging for local and container environments."""

from __future__ import annotations

import json
import logging
import logging.config
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
SENSITIVE_QUERY_PATTERN = re.compile(r"(?i)(?P<prefix>\bticket=)[^&#\s\"',)\]]+")


def _redact_sensitive_query(value: Any, *, field_name: str | None = None) -> Any:
    """Return logging values with queue WebSocket tickets removed."""

    if field_name is not None and field_name.casefold() == "ticket":
        return "<redacted>"
    if isinstance(value, str):
        return SENSITIVE_QUERY_PATTERN.sub(
            r"\g<prefix><redacted>",
            value,
        )
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_query(item) for item in value)
    if isinstance(value, list):
        return [_redact_sensitive_query(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_sensitive_query(item, field_name=str(key)) for key, item in value.items()
        }
    return value


class SensitiveQueryFilter(logging.Filter):
    """Redact one-time credentials before any formatter renders a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_sensitive_query(record.msg)
        record.args = _redact_sensitive_query(record.args)
        if hasattr(record, "path"):
            record.path = _redact_sensitive_query(record.path)
        return True


class JsonFormatter(logging.Formatter):
    """Small dependency-free JSON formatter for production log collectors."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for key in ("method", "path", "status_code", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    """Attach the current request ID to every application log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


def configure_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    """Configure root and Uvicorn logging with the same request context."""

    formatter = "json" if json_logs else "plain"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {"()": RequestIdFilter},
                "sensitive_query": {"()": SensitiveQueryFilter},
            },
            "formatters": {
                "plain": {
                    "format": (
                        "%(asctime)s %(levelname)s %(name)s [request_id=%(request_id)s] %(message)s"
                    )
                },
                "json": {"()": JsonFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "filters": ["sensitive_query", "request_id"],
                    "formatter": formatter,
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )
