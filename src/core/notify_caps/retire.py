
from __future__ import annotations

import sqlite3
from typing import List, Tuple

import structlog

from src.core.notify_caps.store import get_store

logger = structlog.get_logger()


def on_lost(lost: List[Tuple[str, str]]) -> None:
    try:
        store = get_store()
        for _source, ident in lost:
            store.retire_ask(ident)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("notify_caps_retire_failed", error_type=type(exc).__name__)
