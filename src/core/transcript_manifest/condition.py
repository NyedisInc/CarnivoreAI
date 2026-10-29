
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import structlog

from src.core.app_alerts import service
from src.core.db import DatastoreError, db_path_for
from src.core.pipeline.log import log_error
from src.core.transcript_manifest import constants as K
from src.core.transcript_manifest import lookup
from src.core.transcript_manifest.refresh import refresh
from src.core.transcript_manifest.scan import ScanResult

logger = structlog.get_logger(__name__)

_lock = threading.Lock()
_state_dir: Optional[Path] = None
_last: Optional[Dict[str, Any]] = None


def last_scan() -> Optional[Dict[str, Any]]:
    with _lock:
        found = dict(_last) if _last is not None else None
    if found is None:
        from src.core.pipeline import runtime

        engine = runtime.current()
        return dict(engine.scanner.last) if engine is not None and engine.scanner.last is not None else None
    return found


def log_removed(state_dir: Path, result: ScanResult) -> None:
    convs = [r for r in result.removed if r.kind == K.KIND_CONVERSATION]
    if convs:
        logger.warning("transcript_manifest_conversation_removed", removed=len(convs), sample=convs[0].conversation_id)


def run_scan(state_dir: Path, *, claude_roots: Optional[Sequence[Path]] = None,
             codex_home: Optional[str] = None) -> Dict[str, Any]:
    record: Dict[str, Any] = {"status": "ok", "reason": None}
    try:
        result = refresh(db_path_for(state_dir), claude_roots=claude_roots, codex_home=codex_home)
        record.update(result.summary())
        log_removed(state_dir, result)
    except (sqlite3.Error, OSError, DatastoreError) as exc:
        record.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        log_error("transcript_manifest_scan_failed", plugin="manifest", error=exc)
    global _last
    with _lock:
        _last = record
    return record


def retire_removed_alert(db_path: Path) -> None:
    retired = (K.REMOVED_ALERT_KEY, K.RETIRED_FRESHNESS_ALERT_KEY, *K.RETIRED_PIPELINE_ALERT_KEYS)
    for row in service.list_view(db_path, include_closed=False, limit=500)["alerts"]:
        if row["key"] in retired or row["key"].startswith(K.RETIRED_PIPELINE_ALERT_PREFIXES):
            service.dismiss(db_path, row["id"])


def install(state_dir: Path) -> None:
    global _state_dir
    _state_dir = Path(state_dir)
    lookup.configure(db_path_for(_state_dir))
    retire_removed_alert(db_path_for(_state_dir))


def uninstall() -> None:
    global _state_dir, _last
    lookup.configure(None)
    _state_dir = None
    with _lock:
        _last = None
