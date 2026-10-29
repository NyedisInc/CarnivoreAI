
from __future__ import annotations

import os
import re
from typing import Dict



_NO_SERVER_MARKERS = (
    "no server running",
    "failed to connect to server",
    "no current server",
)

_NO_SERVER_CONNECT_ERRNOS = frozenset({"no such file or directory"})

_CONNECT_ERROR_MARKER = "error connecting to"

_CONNECT_ERRNO_RE = re.compile(r"\(([^()]*)\)\s*$")


STDERR_NO_SERVER = "no_server"

STDERR_CONNECT_FAILED = "connect_failed"

STDERR_UNRECOGNISED = "unrecognised"

REASON_CONNECT_FAILED = "connect_failed"


def classify_tmux_stderr(stderr_text: str) -> str:
    lines = [line.strip() for line in (stderr_text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return STDERR_UNRECOGNISED

    connect_verdicts = [
        _classify_connect_line(line)
        for line in lines
        if line.lower().startswith(_CONNECT_ERROR_MARKER)
    ]
    if connect_verdicts:
        for verdict in connect_verdicts:
            if verdict != STDERR_NO_SERVER:
                return verdict
        return STDERR_NO_SERVER

    for line in lines:
        lowered = line.lower()
        if any(lowered.startswith(marker) for marker in _NO_SERVER_MARKERS):
            return STDERR_NO_SERVER

    return STDERR_UNRECOGNISED


def _classify_connect_line(line: str) -> str:
    match = _CONNECT_ERRNO_RE.search(line)
    if match is None:
        return STDERR_UNRECOGNISED
    errno_text = match.group(1).strip().lower()
    if errno_text in _NO_SERVER_CONNECT_ERRNOS:
        return STDERR_NO_SERVER
    return STDERR_CONNECT_FAILED


def looks_like_no_server(stderr_text: str) -> bool:
    return classify_tmux_stderr(stderr_text) == STDERR_NO_SERVER


LISTING_ENV_OVERRIDES = {"LC_ALL": "C"}


def listing_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.update(LISTING_ENV_OVERRIDES)
    return env
