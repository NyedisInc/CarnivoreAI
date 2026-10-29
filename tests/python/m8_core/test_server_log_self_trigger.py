from __future__ import annotations

import logging

from src.core.server_log import redact


def _access(path: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:1", "GET", path, "1.1", 200), None)


def test_server_log_read_access_line_is_dropped() -> None:
    assert redact._keep_record(_access("/api/v1/server-log?tail=200")) is False


def test_other_access_lines_are_kept() -> None:
    assert redact._keep_record(_access("/api/v1/sessions/list")) is True
