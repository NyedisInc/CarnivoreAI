
from __future__ import annotations

import re
from typing import Optional

HEADER = "header"
FRAMES = "frames"
EXCEPTION = "exception"
CHAIN = "chain"

TRACEBACK_START = "Traceback (most recent call last)"
_HEADER = re.compile(r"^(?:ERROR|CRITICAL):\s+Exception in ASGI application\s*$")
_CHAINS = (
    "During handling of the above exception, another exception occurred",
    "The above exception was the direct cause of the following exception",
)
_UVICORN_LEVELS = {"DEBUG": "debug", "INFO": "info", "WARNING": "warn", "ERROR": "error", "CRITICAL": "error"}
_UVICORN_LINE = re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):\s")


def is_header(text: str) -> bool:
    return bool(_HEADER.match(text))


def is_chain(text: str) -> bool:
    return text.startswith(_CHAINS)


def is_traceback_start(text: str) -> bool:
    return text.startswith(TRACEBACK_START)


def is_indented(text: str) -> bool:
    return text[:1] in (" ", "\t")


def uvicorn_level(text: str) -> Optional[str]:
    match = _UVICORN_LINE.match(text)
    return _UVICORN_LEVELS[match.group(1)] if match else None


def advance(state: str, text: str) -> Optional[str]:
    if is_traceback_start(text):
        return FRAMES if state in (HEADER, CHAIN) else None
    if state == FRAMES:
        return FRAMES if is_indented(text) else EXCEPTION
    if state == EXCEPTION and is_chain(text):
        return CHAIN
    return None
