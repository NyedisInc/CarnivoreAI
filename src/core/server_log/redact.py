
from __future__ import annotations

import logging
import sys
from typing import Any, Callable, Dict, List, Optional, TextIO

import structlog

from src.core.stream_redactor import redact_whole

FAILED_EVENT = "log_redaction_failed"
_OWN_KEYS = frozenset({"timestamp", "level"})
_META_KEYS = frozenset({"_record", "_from_structlog"})
_PASS_THROUGH = _OWN_KEYS | _META_KEYS
UVICORN_LOGGER_PREFIX = "uvicorn"
LIBRARY_MIN_LEVEL = logging.WARNING

UVICORN_ACCESS_LOGGER = "uvicorn.access"
SERVER_LOG_READ_PATH_PREFIX = "/api/v1/server-log"

EventDict = Dict[str, Any]


def _map_strings(value: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return fn(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(key): _map_strings(item, fn) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_map_strings(item, fn) for item in value]
    return fn(repr(value))


def make_processor(redact: Callable[[str], str] = redact_whole) -> Callable[[Any, str, EventDict], EventDict]:

    def redact_event(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
        try:
            return {
                key: value if key in _PASS_THROUGH else _map_strings(value, redact)
                for key, value in event_dict.items()
            }
        except Exception as exc:  # noqa: BLE001
            failed: EventDict = {"event": FAILED_EVENT, "error_type": type(exc).__name__}
            for key in _OWN_KEYS:
                if isinstance(event_dict.get(key), str):
                    failed[key] = event_dict[key]
            return failed

    return redact_event


redact_event = make_processor()


def shared_processors() -> List[Callable[[Any, str, EventDict], EventDict]]:
    return [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        redact_event,
    ]


def _is_server_log_read(record: logging.LogRecord) -> bool:
    args = record.args
    if not isinstance(args, tuple) or len(args) < 3 or not isinstance(args[2], str):
        return False
    return args[2].startswith(SERVER_LOG_READ_PATH_PREFIX)


def _keep_record(record: logging.LogRecord) -> bool:
    name = record.name
    if name == UVICORN_ACCESS_LOGGER and _is_server_log_read(record):
        return False
    if name == UVICORN_LOGGER_PREFIX or name.startswith(UVICORN_LOGGER_PREFIX + "."):
        return True
    return record.levelno >= LIBRARY_MIN_LEVEL


def install_stdlib_routing(stream: Optional[TextIO] = None) -> logging.Handler:
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_keep_record)
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    return handler
