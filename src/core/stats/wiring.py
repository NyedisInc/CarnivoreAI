from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import structlog

from . import config, events, rules
from .scheduler import StatsScheduler
from .store import StatsStore

logger = structlog.get_logger()


def initialize(store: StatsStore) -> None:
    store.initialize()
    config.ensure_schema(store)
    rules.initialize(store)
    events.initialize_models(store)


async def start_stats(state: Any, manager: Any, state_dir: Path, config_path: Path) -> None:
    state.stats_store = None
    state.stats_scheduler = None
    try:
        store = StatsStore(state_dir)
        await asyncio.to_thread(initialize, store)
        scheduler = StatsScheduler(store, manager, state, config_path)
        state.stats_store = store
        events.bind(store)
        state.stats_scheduler = scheduler
        scheduler.start()
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        logger.warning('stats_start_failed', error_type=type(exc).__name__)


async def stop_stats(state: Any) -> None:
    events.bind(None)
    scheduler = state.stats_scheduler
    if scheduler is not None:
        await scheduler.aclose()
