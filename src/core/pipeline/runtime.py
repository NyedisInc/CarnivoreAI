
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.pipeline.engine import Engine
from src.cplugs.sdk import pipeline_rows

logger = structlog.get_logger()

_lock = threading.Lock()
_engine: Optional[Engine] = None


def current() -> Optional[Engine]:
    return _engine


def ensure(state_dir: Optional[Path] = None, db_path: Optional[Path] = None) -> Engine:
    """The engine, built but NOT started when it does not exist yet (a lifecycle trigger needs only its milestone writer). Output: Engine.

    Inputs: state_dir, db_path - default this install's (settings, read now). A second call returns the same engine.
    """
    global _engine
    with _lock:
        if _engine is None:
            if state_dir is None or db_path is None:
                from src.config import settings
                from src.core.db import db_path_for

                state_dir = state_dir or settings.get_state_dir()
                db_path = db_path or db_path_for(state_dir)
            _engine = Engine(Path(state_dir), db_path=Path(db_path))
        return _engine


def start(state_dir: Optional[Path] = None, db_path: Optional[Path] = None) -> Engine:
    engine = ensure(state_dir, db_path)
    engine.start()
    return engine


def stop() -> None:
    global _engine
    with _lock:
        engine, _engine = _engine, None
    if engine is not None:
        engine.stop()


def rebuild_plugin(plugin_id: str) -> Dict[str, Any]:
    return start().rebuild_plugin(plugin_id)


def status() -> Dict[str, Any]:
    engine = current()
    body = engine.status() if engine is not None else {"state": "off"}
    extra = pipeline_rows.rows()
    if extra:
        merged = list(body.get("recent", ())) + extra
        body["recent"] = sorted(merged, key=lambda row: row["finished_at"], reverse=True)
    return body


def reset_for_test() -> None:
    stop()
