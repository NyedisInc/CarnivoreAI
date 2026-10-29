
from __future__ import annotations

import subprocess
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core.hosts.remote_host import RemoteHostUnavailable, RemoteSyncOnLoopError
from src.core.hosts.remote_listing import host_status_map, pane_liveness
from src.core.session_status import LIVENESS_LIVE, LIVENESS_UNKNOWN

logger = structlog.get_logger()

CAPTURE_TIMEOUT_SECONDS = 5.0


class RemotePass:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._at: Optional[datetime] = None
        self._maps: Dict[str, Any] = {}
        self._files: Dict[str, Any] = {}
        self._codex: Dict[str, Any] = {}

    def _roll(self, now: datetime) -> None:
        if self._at != now:
            self._at, self._maps, self._files, self._codex = now, {}, {}, {}

    def status_map(self, host: Any, now: datetime) -> Any:
        with self._lock:
            self._roll(now)
            if host.host_key not in self._maps:
                self._maps[host.host_key] = host_status_map(host)
            return self._maps[host.host_key]

    def claude_files(self, manager: Any, host: Any, now: datetime) -> Tuple[Any, Dict[Any, Any]]:
        from src.core.hosts.remote_claude_files import files_for

        with self._lock:
            self._roll(now)
            if host.host_key not in self._files:
                rows = host_open_rows(manager, host)
                files = files_for(host)
                ok = host.is_up and files.refresh(host, rows.values())
                self._files[host.host_key] = (files if ok else None, rows)
            return self._files[host.host_key]

    def codex_files(self, manager: Any, host: Any, now: datetime) -> Tuple[Any, Dict[Any, Any]]:
        from src.core.hosts.remote_codex_files import files_for as codex_files_for

        with self._lock:
            self._roll(now)
            if host.host_key not in self._codex:
                rows = host_open_rows(manager, host)
                files = codex_files_for(host)
                ok = host.is_up and files.refresh(host)
                self._codex[host.host_key] = (files if ok else None, rows)
            return self._codex[host.host_key]


def host_open_rows(manager: Any, host: Any) -> Dict[Tuple[str, int], Optional[str]]:
    import sqlite3
    from contextlib import closing

    from src.core.db_models import SESSION_LIFECYCLE_RUNNING
    from src.core.hosts.ddl import host_scope

    try:
        conn = manager._datastore_connection()
        if conn is None:
            return {}
        with closing(conn):
            scope_sql, scope_params = host_scope(conn, host.host_key)
            found = conn.execute(
                "SELECT tmux_name, tmux_created_epoch, claude_session_uuid FROM sessions "
                f"WHERE tmux_socket = ?{scope_sql} AND lifecycle = ? "
                "AND tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL",
                (host.socket, *scope_params, SESSION_LIFECYCLE_RUNNING)).fetchall()
    except (sqlite3.Error, OSError) as exc:
        logger.info("remote_open_rows_unreadable", host=host.host_key, error=str(exc))
        return {}
    return {(str(r[0]), int(r[1])): (str(r[2]) if r[2] else None) for r in found}


def _capture(backend: Any) -> Optional[str]:
    from src.core.tmux_transport.target import exact_pane_target

    try:
        rc, out, _ = backend._run_tmux_sync(
            "capture-pane", "-p", "-S", "0", "-t", exact_pane_target(backend.tmux_session),
            check=False, timeout=CAPTURE_TIMEOUT_SECONDS)
    except (RemoteHostUnavailable, RemoteSyncOnLoopError, subprocess.TimeoutExpired,
            ValueError) as exc:
        logger.info("remote_attention_capture_failed", host=backend.host_key, error=str(exc))
        return None
    return out.decode("utf-8", errors="replace") if rc == 0 else None


def read_remote_evidence(manager: Any, remote_pass: RemotePass, session_id: str,
                         backend: Any, now: datetime) -> Optional[Any]:
    from dataclasses import replace

    from src.core.agent_family_display import resolve_family_for_display
    from src.core.attention.codex_pane import classify_codex_pane
    from src.core.attention.evidence import FAMILY_CLAUDE, FAMILY_CODEX, Evidence
    from src.core.attention.pane_markers import classify_pane_tail
    from src.core.listing_attention import attention_reads_for_name

    status_map = remote_pass.status_map(backend.host, now)
    if not status_map.complete:
        return None
    liveness, pane_row = pane_liveness(status_map, backend)
    if pane_row is None:
        liveness = LIVENESS_UNKNOWN
    name = str(backend.tmux_session)
    epoch = manager._instance_epochs.get(session_id)
    measured = (pane_row or {}).get("created_at_epoch")
    if epoch is not None and measured is not None and epoch != measured:
        return None
    session = manager._registry.sessions.get(session_id)
    family, _ = resolve_family_for_display(getattr(session, "agent_type", None),
                                           manager._wrappers_reader())
    family_name = family.name if family else None
    epoch = measured if measured is not None else epoch
    files, rows = (remote_pass.claude_files(manager, backend.host, now)
                   if family_name in (None, FAMILY_CLAUDE) else (None, {}))
    row_uuid = rows.get((name, epoch)) if epoch is not None else None
    if files is None:
        registry, transcript = attention_reads_for_name(
            name, registry_index={}, session_started_epoch=None, claude_session_uuid=None,
            working_dir=None, now=now)
    else:
        registry, transcript = attention_reads_for_name(
            name, registry_index=files.registry, session_started_epoch=epoch,
            claude_session_uuid=row_uuid, working_dir=None, now=now,
            transcript_reader=lambda uuid, _wd, now=None: files.transcript_facts(
                backend.host, uuid, now))
    uuid = ((registry.session_uuid or registry.record_session_uuid or row_uuid)
            if registry.instance_present else row_uuid)
    pane, codex, codex_bind = None, None, None
    if family_name == FAMILY_CODEX:
        from src.core.hosts.remote_codex_files import codex_evidence_for

        codex, codex_bind, uuid = codex_evidence_for(
            manager, remote_pass, backend, pane_row or {}, epoch, now)
    if liveness == LIVENESS_LIVE and family_name in (None, FAMILY_CLAUDE, FAMILY_CODEX):
        text = _capture(backend)
        if text is not None:
            if codex is not None:
                codex = replace(codex, pane=classify_codex_pane(text))
            else:
                pane = classify_pane_tail(text.splitlines())
    return Evidence(
        tmux_liveness=liveness, agent_family=family_name, registry=registry,
        transcript=transcript, pane=pane, codex=codex, now=now,
        identity=(backend.socket_name, name, epoch, None, uuid), codex_bind_uuid=codex_bind)

