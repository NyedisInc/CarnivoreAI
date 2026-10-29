
from __future__ import annotations

from typing import Any, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)

MAX_REMEMBERED = 512

_SEEN: Set[Tuple[str, str]] = set()


def warn_once(event: str, key: str, **context: Any) -> bool:
    ident = (event, key)
    if ident in _SEEN:
        return False
    if len(_SEEN) >= MAX_REMEMBERED:
        _SEEN.clear()
    _SEEN.add(ident)
    logger.warning(event, **context)
    return True


def reset_warnings() -> None:
    _SEEN.clear()
