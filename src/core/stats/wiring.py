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


def _ensure_carnivore_pack_indexes(state_dir: Path) -> None:
    from src.core.db import connect, db_path_for

    app_db = db_path_for(state_dir)
    if not app_db.exists():
        return
    index_specs = (
        ("pack_rollups", "CREATE INDEX IF NOT EXISTS pack_rollups_peer_hour ON pack_rollups(peer_install_id, hour)"),
        ("pack_rollups", "CREATE INDEX IF NOT EXISTS pack_rollups_conv ON pack_rollups(conversation_id, peer_install_id, hour, project)"),
        ("pack_rollup_counters", "CREATE INDEX IF NOT EXISTS pack_rollup_counters_conv ON pack_rollup_counters(conversation_id, peer_install_id, hour, project)"),
    )
    try:
        conn = connect(app_db, create=False)
        try:
            present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for tbl, ddl in index_specs:
                if tbl in present:
                    conn.execute(ddl)
            if "pack_rollups" in present:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(pack_rollups)")}
                if "agent_name" in cols:
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS pack_rollups_agent_name "
                        "ON pack_rollups(hour, conversation_id, agent_name) WHERE agent_name IS NOT NULL"
                    )
            conn.commit()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        logger.debug("pack_rollup_index_ensure_skipped", error=type(exc).__name__)


def initialize(store: StatsStore) -> None:
    store.initialize()
    config.ensure_schema(store)
    rules.initialize(store)
    events.initialize_models(store)
    _ensure_carnivore_pack_indexes(store.state_dir)


async def start_stats(state: Any, manager: Any, state_dir: Path, config_path: Path) -> None:
    from src.core.stats.plugin import progress as stats_progress

    state.stats_store = None
    state.stats_scheduler = None
    try:
        store = StatsStore(state_dir)
        await asyncio.to_thread(initialize, store)
        stats_progress.cached_progress(state_dir, block=False)
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
