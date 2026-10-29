
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from src.core.transcript_source import constants as C

SCOPE_HUMAN: str = "human"
SCOPE_SUBSESSIONS: str = "human+subsessions"
SCOPE_ALL: str = "all"

_ENTRYPOINT = re.compile(rb'"entrypoint"\s*:\s*"([^"\\]{1,64})"')


def entrypoint_is_subsession(head: bytes) -> bool:
    found = _ENTRYPOINT.search(head)
    return bool(found) and found.group(1).decode("ascii", "replace").startswith(
        C.SUBSESSION_ENTRYPOINT_PREFIX)


def is_subsession(transcript: Path) -> bool:
    try:
        with open(transcript, "rb") as handle:
            head = handle.read(C.ENTRYPOINT_SCAN_BYTES)
    except OSError:
        return False
    return entrypoint_is_subsession(head)


def includes_session(scope: str, family: str, transcript: Path, head: Optional[bytes] = None) -> bool:
    if scope != SCOPE_HUMAN or family == C.FAMILY_CODEX:
        return True
    return not (is_subsession(transcript) if head is None else entrypoint_is_subsession(head))


def includes_subagents(scope: str) -> bool:
    return scope == SCOPE_ALL
