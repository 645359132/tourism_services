"""Predictable application logging for local and container environments."""

from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


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
            "filters": {"request_id": {"()": RequestIdFilter}},
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
                    "filters": ["request_id"],
                    "formatter": formatter,
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )
