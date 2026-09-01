"""Sensitive query values must never survive logging interpolation."""

from __future__ import annotations

import logging

import pytest

from app.core.logging import SensitiveQueryFilter


@pytest.mark.parametrize(
    ("message", "arguments"),
    [
        (
            "WebSocket /api/v1/ws/queues/abc?ticket=msg-secret&mode=live",
            (),
        ),
        (
            '127.0.0.1 - "WebSocket %s" [accepted]',
            ("/api/v1/ws/queues/abc?ticket=tuple-secret",),
        ),
        (
            "WebSocket %(path)s ticket=%(ticket)s",
            {
                "path": "/api/v1/ws/queues/abc?ticket=dict-path-secret",
                "ticket": "dict-value-secret",
            },
        ),
    ],
)
def test_sensitive_query_filter_redacts_message_and_argument_shapes(
    message: str,
    arguments: tuple[object, ...] | dict[str, object],
) -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=arguments,
        exc_info=None,
    )

    assert SensitiveQueryFilter().filter(record) is True
    rendered = record.getMessage()

    assert "msg-secret" not in rendered
    assert "tuple-secret" not in rendered
    assert "dict-path-secret" not in rendered
    assert "dict-value-secret" not in rendered
    assert "ticket=<redacted>" in rendered
