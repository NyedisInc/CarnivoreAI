
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from src.core.deepsearch import constants as K
from src.core.deepsearch.cache import db


def info(state_dir: Path) -> Dict[str, Any]:
    """``{state, built_at}``; a cache file that does not exist yet is ``building`` with no time. Output: dict."""
    if not db.cache_path(state_dir).exists():
        return {"state": K.CACHE_BUILDING, "built_at": None}
    conn = db.open_cache(state_dir)
    try:
        state, built_at = conn.execute(f"SELECT state, built_at FROM {K.CACHE_META_TABLE} WHERE id = 1").fetchone()
    finally:
        conn.close()
    return {"state": state, "built_at": built_at}


def state(state_dir: Path) -> str:
    return info(state_dir)["state"]


def mark_ready(state_dir: Path) -> None:
    conn = db.open_cache(state_dir)
    try:
        conn.execute(f"UPDATE {K.CACHE_META_TABLE} SET state = ?, built_at = COALESCE(built_at, ?) WHERE id = 1",
                     (K.CACHE_READY, datetime.now(timezone.utc).isoformat()))
    finally:
        conn.close()


def reset(state_dir: Path) -> None:
    db.remove_files(db.cache_path(state_dir))
