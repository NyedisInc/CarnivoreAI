
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

import structlog

from src.core.pipeline import plugin_db, registry
from src.core.pipeline.observe import TRIGGER_REBUILD

if TYPE_CHECKING:
    from src.core.pipeline.engine import Engine

logger = structlog.get_logger()

REBUILD_SUFFIX: str = ".rebuilding"


class UnknownPlugin(LookupError):
    pass


def _remove(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        return


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _swap(engine: "Engine", plugin: Any) -> int:
    from src.core.db import transaction

    old = plugin_db.db_path(engine.state_dir, plugin)
    fresh = old.with_name(old.name + REBUILD_SUFFIX)
    with plugin_db.lock_for(plugin.id):
        for leftover in (fresh, Path(f"{fresh}-wal"), Path(f"{fresh}-shm")):
            _remove(leftover)
        new_conn = plugin_db.open_db(engine.state_dir, plugin, path=fresh)
        try:
            try:
                with transaction(new_conn):
                    if plugin.rebuild is not None:
                        plugin.rebuild(new_conn)
                    if plugin.carry_over is not None and old.exists():
                        with closing(sqlite3.connect(f"file:{old}?mode=ro", uri=True, timeout=30.0)) as old_conn:
                            plugin.carry_over(old_conn, new_conn)
            except Exception as exc:  # noqa: BLE001
                raise plugin_db.PluginUnavailable(f"rebuild failed: {type(exc).__name__}: {exc}") from exc
            new_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            new_conn.close()
        dropped = _size(old) + _size(Path(f"{old}-wal"))
        if old.exists():
            with closing(sqlite3.connect(str(old), isolation_level=None, timeout=30.0)) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        os.replace(fresh, old)
        for leftover in (Path(f"{old}-wal"), Path(f"{old}-shm"), Path(f"{fresh}-wal"), Path(f"{fresh}-shm")):
            _remove(leftover)
    return dropped


def rebuild_plugin(engine: "Engine", plugin_id: str) -> Dict[str, Any]:
    plugin = registry.find(plugin_id, engine.plugins)
    if plugin is None:
        raise UnknownPlugin(plugin_id)
    engine.begin_rebuild(plugin_id)
    error: Optional[str] = "interrupted"
    try:
        dropped = _swap(engine, plugin)
        engine.dirty.forget_plugin(plugin_id)
        targets = engine.scanner.targets_for(plugin)
        for target in targets:
            engine.mark_dirty(target, TRIGGER_REBUILD)
        error = None
    except (plugin_db.PluginUnavailable, sqlite3.Error, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        engine.end_rebuild(plugin_id, error=error)
    logger.info("pipeline_plugin_rebuilt", plugin=plugin.id, dropped_bytes=dropped, files_marked=len(targets))
    return {"plugin": plugin.id, "dropped_bytes": dropped, "files_marked": len(targets)}
