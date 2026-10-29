from __future__ import annotations

import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog

from . import answers, config
from .store import StatsStore

logger = structlog.get_logger()

MIN_FREE_BYTES = 64 * 1024 * 1024


class StatsStillOn(RuntimeError):
    pass


class NotEnoughSpace(RuntimeError):

    def __init__(self, free: int, needed: int) -> None:
        super().__init__("not enough free disk space")
        self.free, self.needed = free, needed


@dataclass
class ClearJob:
    state: str = "idle"
    phase: str = ""
    bytes_before: int | None = None
    bytes_after: int | None = None
    error: str = ""
    finished_at: float | None = None

    def public(self) -> dict:
        reclaimed = None
        if self.bytes_before is not None and self.bytes_after is not None:
            reclaimed = max(0, self.bytes_before - self.bytes_after)
        return {"state": self.state, "phase": self.phase, "bytes_before": self.bytes_before,
                "bytes_after": self.bytes_after, "reclaimed_bytes": reclaimed,
                "error": self.error, "finished_at": self.finished_at}


def file_bytes(store: StatsStore) -> int:
    return sum(p.stat().st_size for suffix in ("", "-wal", "-shm")
               if (p := store.db_path.with_name(store.db_path.name + suffix)).exists())


def free_space(store: StatsStore) -> int:
    store.state_dir.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(store.state_dir).free


def clear_stats(store: StatsStore, job: ClearJob,
                free_bytes: Callable[[StatsStore], int] = free_space) -> ClearJob:
    from src.core.pipeline import plugin_db, runtime
    from src.core.stats.plugin import PLUGIN_ID

    if config.get_settings(store)["enabled"]:
        raise StatsStillOn("turn stats off before clearing")
    free = free_bytes(store)
    if free < MIN_FREE_BYTES:
        raise NotEnoughSpace(free, MIN_FREE_BYTES)
    job.state, job.phase, job.error = "running", "rebuilding", ""
    job.bytes_before = file_bytes(store)
    try:
        runtime.rebuild_plugin(PLUGIN_ID)
    except (OSError, sqlite3.Error, plugin_db.PluginUnavailable) as exc:
        job.state, job.error = "failed", type(exc).__name__
        logger.warning("stats_clear_failed", error_type=type(exc).__name__)
        raise
    answers.purge(store)
    job.bytes_after = file_bytes(store)
    job.state, job.phase, job.finished_at = "done", "", time.time()
    return job
