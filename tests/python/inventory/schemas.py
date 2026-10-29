
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from src.core import message_block_ddl, message_block_search_ddl, message_host_ddl, message_model_ddl
from src.core.attention_history.store import AttentionHistoryStore
from src.core.bookmarks.store import BookmarkStore
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.inventory import registry_side as side
from src.core.session_token_usage.reader_state_store import ReaderStateStore
from src.core.skill_fires.store import SkillFireStore
from src.core.spectator_links_store import SpectatorLinksStore
from src.core.pipeline import plugin_db
from src.core.stats import answers as stats_answers, wiring as stats_wiring
from src.core.stats.store import StatsStore
from src.core.deepsearch.pipeline_plugin import DEEPSEARCH
from src.core.work import storage as work_storage
from src.core.work.importer import ready

SESSION_CONVERSATIONS_DDL = """
CREATE TABLE session_conversations (
  id INTEGER PRIMARY KEY, session_uuid TEXT NOT NULL, conversation_id TEXT NOT NULL,
  agent_family TEXT NOT NULL DEFAULT 'claude', sequence INTEGER NOT NULL, started_at TEXT, ended_at TEXT, ended_reason TEXT,
  parent_conversation_id TEXT, first_prompt TEXT NOT NULL DEFAULT '', link_source TEXT NOT NULL DEFAULT 'live',
  recorded_at TEXT NOT NULL, UNIQUE (session_uuid, conversation_id));
"""


def build_main(state_dir: Path) -> Path:
    assert ensure_db_migrated(state_dir, 4, "0.0.0").status == "ok"
    path = db_path_for(state_dir)
    with closing(connect(path)) as conn:
        for module in (message_model_ddl, message_host_ddl, message_block_ddl, message_block_search_ddl):
            for name in sorted(n for n in dir(module) if n.startswith("DDL_V")):
                value = getattr(module, name)
                for statement in (value if isinstance(value, (tuple, list)) else [value]):
                    conn.execute(statement)
        conn.execute(SESSION_CONVERSATIONS_DDL)
        conn.commit()
    store = SpectatorLinksStore(str(path))
    asyncio.run(store.init())
    ready.ensure(path, work_storage.folder(state_dir), state_dir)
    ready.forget(path)
    return path


def build_side(state_dir: Path) -> Dict[str, Path]:
    from src.core.automations.store_schema import storage_for
    from src.core.deepsearch.cache import db as cache_db

    now = datetime.now(timezone.utc)
    paths = {label: side.side_db_path(state_dir, label) for label in side.SIDE_DBS}
    paths[side.BOOKMARKS].parent.mkdir(parents=True, exist_ok=True)
    BookmarkStore(paths[side.BOOKMARKS]).list_recent(1)
    AttentionHistoryStore(paths[side.ATTENTION]).record("schema-probe", "question", now)
    with closing(sqlite3.connect(paths[side.ATTENTION])) as conn, conn:
        conn.execute("DELETE FROM attention_events")
    storage_for(state_dir).connect(True).close()
    cache_db.open_cache(state_dir).close()
    plugin_db.open_db(state_dir, DEEPSEARCH).close()
    stats_wiring.initialize(StatsStore(state_dir))
    with closing(sqlite3.connect(paths[side.STATS])) as conn, conn:
        for statement in stats_answers._SCHEMA:
            conn.execute(statement)
    ReaderStateStore(paths[side.READER_STATE]).load("probe", "v1", 1)
    SkillFireStore(paths[side.SKILL_FIRES]).count("probe")
    return paths
