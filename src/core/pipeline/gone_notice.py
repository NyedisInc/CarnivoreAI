
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

import structlog

from src.core.pipeline import contract as C
from src.core.pipeline import plugin_db
from src.core.pipeline.deliver import FileTarget

logger = structlog.get_logger()

_CursorRow = Tuple[str, str, str]


def _cursors_of(state_dir: Path, plugin: C.Plugin, conversation_id: str) -> List[_CursorRow]:
    with plugin_db.lock_for(plugin.id):
        conn = plugin_db.pooled_db(state_dir, plugin)
        try:
            rows = conn.execute(f"SELECT path, family, file_kind FROM {C.CURSORS_TABLE} WHERE conversation_id = ?", (conversation_id,)).fetchall()
        except sqlite3.Error:
            plugin_db.discard_pooled(state_dir, plugin)
            raise
    return [(r[0], r[1], r[2]) for r in rows]


def mark_files_gone(state_dir: Path, plugins: Sequence[C.Plugin], conversation_id: str, mark: Callable[[FileTarget, str], bool], trigger: str) -> int:
    marked = 0
    for plugin in plugins:
        if not plugin.per_file_removal:
            continue
        try:
            cursors = _cursors_of(state_dir, plugin, conversation_id)
        except (plugin_db.PluginUnavailable, sqlite3.Error) as exc:
            logger.warning("pipeline_files_gone_unreadable", plugin=plugin.id, conversation_id=conversation_id, error_type=type(exc).__name__, error=str(exc)[:200])
            continue
        for path, family, kind in cursors:
            mark(FileTarget(path, conversation_id, family, kind), trigger)
            marked += 1
    logger.info("pipeline_files_gone_marked", conversation_id=conversation_id, files=marked)
    return marked
