
from __future__ import annotations

MAX_LOGGED_CHARS = 200


def log_value(value: object) -> str:
    return repr(value)[:MAX_LOGGED_CHARS]
