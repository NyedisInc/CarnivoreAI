
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

import structlog

from src.plugins.sdk.session_chains import ChainSnapshot, RunningScan, SessionChainsUnreadable, SessionFacts

logger = structlog.get_logger()

_MAX_REGISTRY_BYTES = 64 * 1024


def _epoch(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _last_active(work_at: Optional[str], seen_at: Optional[str], created_at: Optional[str]) -> Optional[float]:
    times = [t for t in (_epoch(work_at), _epoch(seen_at)) if t is not None]
    return max(times) if times else _epoch(created_at)


def _is_asleep(lifecycle: str, source: Optional[str], conversation: Optional[str]) -> bool:
    from src.core import session_sleep as sleep  # noqa: PLC0415

    if lifecycle != sleep.SESSION_LIFECYCLE_STOPPED:
        return False
    return source in sleep.SLEEP_SOURCES or (source == sleep.LIFECYCLE_SOURCE_PANE_DEAD and bool(conversation))


def snapshot_from(conn: sqlite3.Connection) -> ChainSnapshot:
    from src.core.lineage import constants as K  # noqa: PLC0415
    from src.core.lineage import graph  # noqa: PLC0415

    try:
        if not graph.ready(conn):
            raise SessionChainsUnreadable("the lineage tables are not there")
        rows = conn.execute(
            "SELECT session_uuid, title, project_id, host_key, lifecycle, lifecycle_source, archived_at, claude_session_uuid, "
            "last_work_at, last_seen_running_at, created_at, working_dir FROM sessions").fetchall()
        marks = ",".join("?" for _ in K.CONTINUATION_KINDS)
        edges = conn.execute(
            f"SELECT parent_id, child_type, child_id FROM {K.EDGES_TABLE} WHERE parent_type = ? AND child_type IN (?, ?) "
            f"AND edge_kind IN ({marks})", (K.NODE_CONVERSATION, K.NODE_CONVERSATION, K.NODE_SESSION, *K.CONTINUATION_KINDS)).fetchall()
    except sqlite3.Error as exc:
        raise SessionChainsUnreadable(type(exc).__name__) from exc
    sessions = tuple(
        SessionFacts(session_uuid=str(r[0]), title=r[1], project_id=int(r[2]) if r[2] is not None else None, host_key=str(r[3] or "local"),
                     lifecycle=str(r[4] or "unknown"), lifecycle_source=r[5], archived=r[6] is not None,
                     asleep=_is_asleep(str(r[4] or "unknown"), r[5], r[7]), claude_session_uuid=r[7] or None,
                     last_active_epoch=_last_active(r[8], r[9], r[10]), working_dir=r[11] or None) for r in rows)
    by_conv: Dict[str, Set[str]] = {}
    by_session: Dict[str, Set[str]] = {}
    for parent, child_type, child in edges:
        (by_conv if child_type == K.NODE_CONVERSATION else by_session).setdefault(str(child), set()).add(str(parent))
    return ChainSnapshot(sessions, {k: frozenset(v) for k, v in by_conv.items()}, {k: frozenset(v) for k, v in by_session.items()})


def read_snapshot() -> ChainSnapshot:
    from src.config import settings  # noqa: PLC0415
    from src.core.db import DatastoreError, db_path_for  # noqa: PLC0415
    from src.core.db_reuse.core_read import lend_pooled_or_raise  # noqa: PLC0415

    try:
        with closing(lend_pooled_or_raise(db_path_for(settings.get_state_dir()))) as conn:
            return snapshot_from(conn)
    except (sqlite3.Error, DatastoreError) as exc:
        logger.warning("cplug_session_chains_unreadable", error_type=type(exc).__name__, error=str(exc)[:200])
        raise SessionChainsUnreadable(type(exc).__name__) from exc


def running_from(directories: Iterable[Path]) -> RunningScan:
    from src.core.attention.registry_index import pid_is_running  # noqa: PLC0415
    from src.core.attention.registry_record import REG_OK, load_registry_blob  # noqa: PLC0415

    held: Set[str] = set()
    unreadable = 0
    for base in directories:
        try:
            names = sorted(n for n in os.listdir(base) if n.endswith(".json"))
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("offload_registry_unlistable", path=str(base), error_type=type(exc).__name__, error=str(exc)[:200])
            unreadable += 1
            continue
        for name in names:
            try:
                with open(Path(base) / name, "rb") as handle:
                    blob = handle.read(_MAX_REGISTRY_BYTES)
            except OSError:
                unreadable += 1
                continue
            record = load_registry_blob(name, blob)
            if record.verdict != REG_OK:
                unreadable += 1
                continue
            if record.session_uuid and pid_is_running(record.pid) is not False:
                held.add(record.session_uuid)
    return RunningScan(frozenset(held), unreadable)


def read_running() -> RunningScan:
    from src.core.claude_config.profile_roots import claude_registry_roots  # noqa: PLC0415

    return running_from(claude_registry_roots())

