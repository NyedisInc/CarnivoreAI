
from __future__ import annotations

import os
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Dict, Optional

import structlog

from src.core.artifact_freshness.verdict import (
    FRESHNESS_CURRENT,
    classify_freshness,
    utc_now_iso,
)
from src.core.db_integrity_pair import check_every_database
from src.core.db import (
    DatastoreUnreadableError,
    connect,
    db_path_for,
    get_meta,
    integrity_check,
)
from src.core.db_models import META_INSTALL_ID
from src.core.json_artifact import atomic_write_json, read_json_object

logger = structlog.get_logger()

INTEGRITY_DIRNAME = "db-integrity"

LATEST_FILENAME = "latest.json"

DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60

STALE_INTERVAL_MULTIPLIER = 2

ENABLE_ENV = "CLOUDE_DB_INTEGRITY_CHECK"

INTERVAL_ENV = "CLOUDE_DB_INTEGRITY_CHECK_INTERVAL"

TEST_MODE_ENV = "CLOUDE_TEST_MODE"

RUN_OK = "ok"
RUN_FAILED = "failed"
RUN_CANNOT_DETERMINE = "cannot_determine"
RUN_CANCELLED = "cancelled"

SOURCE_SCHEDULED = "scheduled"
SOURCE_BOOT = "boot"

_FALSEY = frozenset({"0", "false", "off", "no"})
_TRUTHY = frozenset({"1", "true", "on", "yes"})


def artifact_dir(state_dir: Path) -> Path:
    return Path(state_dir) / INTEGRITY_DIRNAME


def latest_path(state_dir: Path) -> Path:
    return artifact_dir(state_dir) / LATEST_FILENAME


def integrity_check_enabled() -> bool:
    raw = os.environ.get(ENABLE_ENV)
    if raw is not None:
        value = raw.strip().lower()
        if value in _TRUTHY:
            return True
        return value not in _FALSEY
    return not os.environ.get(TEST_MODE_ENV)


def resolve_interval_seconds() -> int:
    raw = os.environ.get(INTERVAL_ENV, "").strip()
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        logger.warning("db_integrity_interval_unparseable", value=raw)
        return DEFAULT_INTERVAL_SECONDS
    if value <= 0:
        logger.warning("db_integrity_interval_not_positive", value=raw)
        return DEFAULT_INTERVAL_SECONDS
    return value


def resolve_stale_after_seconds(interval_seconds: Optional[int] = None) -> int:
    interval = (
        interval_seconds if interval_seconds is not None
        else resolve_interval_seconds()
    )
    return int(interval) * STALE_INTERVAL_MULTIPLIER


def db_size_bytes(db_path: Path) -> Optional[int]:
    try:
        return Path(db_path).stat().st_size
    except OSError:
        return None


def read_verdict(state_dir: Path) -> Optional[Dict[str, Any]]:
    return read_json_object(
        latest_path(state_dir), log_event="db_integrity_artifact_unreadable",
    )


def write_verdict(state_dir: Path, record: Dict[str, Any]) -> bool:
    return atomic_write_json(
        latest_path(state_dir), record,
        log_event="db_integrity_artifact_write_failed",
    )


def run_integrity_check_once(
    state_dir: Path, *, cancel: Optional[Event] = None,
) -> Dict[str, Any]:
    db_path = db_path_for(state_dir)
    started = time.monotonic()
    install_id: Optional[str] = None
    if cancel is not None and cancel.is_set():
        return publish_run(
            state_dir, RUN_CANCELLED, db_path, started,
            "the check was asked to stop before it opened the database",
        )
    parts: list = []
    try:
        with closing(connect(db_path, create=False)) as conn:
            install_id = get_meta(conn, META_INSTALL_ID)
            verdict = integrity_check(conn)
            parts = check_every_database(state_dir, verdict)
    except DatastoreUnreadableError as exc:
        return publish_run(
            state_dir, RUN_CANNOT_DETERMINE, db_path, started, str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return publish_run(
            state_dir, RUN_CANNOT_DETERMINE, db_path, started,
            f"{type(exc).__name__}: {exc}",
        )
    if verdict == "ok":
        return publish_run(
            state_dir, RUN_OK, db_path, started, None, install_id=install_id,
            parts=parts,
        )
    return publish_run(
        state_dir, RUN_FAILED, db_path, started, verdict,
        install_id=install_id, parts=parts,
    )


def publish_run(
    state_dir: Path, status: str, db_path: Path, started: float,
    detail: Optional[str], *, install_id: Optional[str] = None,
    source: str = SOURCE_SCHEDULED, parts: Optional[list] = None,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "status": status,
        "finished_at": utc_now_iso(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "detail": detail,
        "db_path": str(db_path),
        "install_id": install_id,
        "db_size_bytes": db_size_bytes(db_path),
        "source": source,
        "databases": parts or [],
    }
    written = write_verdict(state_dir, record)
    logger.info(
        "db_integrity_check_finished",
        status=status,
        source=source,
        duration_seconds=record["duration_seconds"],
        artifact_written=written,
    )
    return record


def seconds_until_due(
    state_dir: Path, interval_seconds: int, *,
    now: Optional[datetime] = None,
) -> float:
    record = read_verdict(state_dir)
    freshness, age, _why = classify_freshness(
        record, now=now,
        stale_after_seconds=resolve_stale_after_seconds(interval_seconds),
    )
    if freshness != FRESHNESS_CURRENT or age is None:
        return 0.0
    return max(0.0, float(interval_seconds) - age)


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "ENABLE_ENV",
    "INTERVAL_ENV",
    "RUN_CANCELLED",
    "RUN_CANNOT_DETERMINE",
    "RUN_FAILED",
    "RUN_OK",
    "SOURCE_BOOT",
    "SOURCE_SCHEDULED",
    "FRESHNESS_CURRENT",
    "artifact_dir",
    "db_size_bytes",
    "integrity_check_enabled",
    "publish_run",
    "latest_path",
    "read_verdict",
    "resolve_interval_seconds",
    "resolve_stale_after_seconds",
    "run_integrity_check_once",
    "seconds_until_due",
    "write_verdict",
]
