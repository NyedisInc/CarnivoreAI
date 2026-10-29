
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.core.db import DatastoreError
from src.core.pipeline import lag as pipeline_lag
from src.core.stats.plugin.pipeline_plugin import STATS
from src.core.stats_feed.model import SourceState
from src.core.stats_feed.reader import Snapshot

CATCH_UP_BYTES: int = 4 * 1024 * 1024

HELD: Tuple[str, ...] = ("plugin_off", "needs_approval", "paused")


@dataclass(frozen=True)
class LocalState:

    word: SourceState
    lag_bytes: Optional[int]
    behind_conversations: Optional[int]
    data_through: Optional[float]


def read_lag(state_dir: Path, db_path: Path) -> Tuple[Optional[int], Optional[int]]:
    try:
        found = pipeline_lag.lag_of(state_dir, db_path, STATS)
    except (sqlite3.Error, OSError, DatastoreError):
        return None, None
    return found.lag_bytes, found.behind_conversations


def local_state(state_dir: Path, snap: Snapshot, lag: Tuple[Optional[int], Optional[int]]) -> LocalState:
    lag_bytes, behind = lag
    word: SourceState = "ok"
    if not snap.enabled:
        word = "stats_off"
    elif (lag_bytes or 0) >= CATCH_UP_BYTES:
        word = "catching_up"
    return LocalState(word, lag_bytes, behind, snap.last_delivery_at)
