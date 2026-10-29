
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Callable, Dict, List

from src.core import session_sleep
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.federation.shadow_rows import PEER_ORIGIN
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.models import SessionInfo


def owned_rows(infos: List[SessionInfo]) -> List[SessionInfo]:
    return [i for i in infos
            if i.host_key == LOCAL_HOST_KEY and not str(i.session.id).startswith(REMOTE_ID_PREFIX)
            and i.origin_install_id is None]


def _stamp_lookup(conn: sqlite3.Connection, rows: List[SessionInfo]) -> Dict[int, tuple[str, str | None]]:
    ids = sorted({i.session_row_id for i in rows if i.session_row_id is not None})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {int(r[0]): (str(r[1]), r[2]) for r in conn.execute(
        f"SELECT id, session_uuid, claude_title FROM sessions WHERE host_key = 'local' AND id IN ({marks})", ids)}


def _uid_lookup(conn: sqlite3.Connection, rows: List[SessionInfo]) -> Dict[int, tuple[str | None, str | None]]:
    ids = sorted({i.project_id for i in rows if i.project_id is not None})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {int(r[0]): (r[1], r[2]) for r in conn.execute(
        f"SELECT p.id, p.uid, c.uid FROM projects p LEFT JOIN companies c ON c.id = p.company_id WHERE p.id IN ({marks})", ids)}


def serve_to_peer(infos: List[SessionInfo], open_db: Callable[[], sqlite3.Connection]) -> List[SessionInfo]:
    kept = owned_rows(infos)
    with closing(open_db()) as conn:
        install_id = get_meta(conn, META_INSTALL_ID)
        uuids = _stamp_lookup(conn, kept)
        uids = _uid_lookup(conn, kept)
    return [_slim(i, install_id, uuids.get(i.session_row_id), uids.get(i.project_id, (None, None))) for i in kept]


def serve_asleep_to_peer(open_db: Callable[[], sqlite3.Connection]) -> List[Dict[str, object]]:
    with closing(open_db()) as conn:
        install_id = get_meta(conn, META_INSTALL_ID)
        rows = session_sleep.asleep_rows(conn)
    return [{"origin_install_id": install_id, "session_uuid": r["session_uuid"], "tmux_session": r.get("tmux_name"),
             "label": r.get("title"), "working_dir": r.get("working_dir"), "agent_type": r.get("agent_type"),
             "agent_family": r.get("agent_family"), "agent_family_source": r.get("agent_family_source"),
             "source": r.get("lifecycle_source") if r.get("lifecycle_source") in session_sleep.SLEEP_SOURCES
             else session_sleep.LIFECYCLE_SOURCE_SLEPT}
            for r in rows if r.get("host_key", LOCAL_HOST_KEY) == LOCAL_HOST_KEY and r.get("origin") != PEER_ORIGIN]


def _slim(info: SessionInfo, install_id: object, detail: tuple[str, str | None] | str | None,
          uids: tuple[str | None, str | None] = (None, None)) -> SessionInfo:
    uuid, title = (detail if isinstance(detail, tuple) else (detail, None))
    return info.model_copy(update={
        "origin_install_id": install_id, "session_uuid": uuid, "project_uid": uids[0], "company_uid": uids[1],
        "claude_title": title, "session": info.session.model_copy(update={"pty_pid": None}),
        "local_servers": [], "parent_session_id": None, "project_id": None, "project_name": None})
