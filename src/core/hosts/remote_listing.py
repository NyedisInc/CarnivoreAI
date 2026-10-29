
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

import structlog

from src.core.hosts.identity import instance_name, is_remote_backend
from src.core.session_status_map import StatusMap, listing_proves_alive, status_map_from_listing

logger = structlog.get_logger()

_PROBE_SESSION_ID = "__status_probe__"


@dataclass(frozen=True)
class RemoteTarget:

    session_id: str
    host: Any
    name: str
    backend: Any


@dataclass(frozen=True)
class RemoteGather:

    maps: Dict[str, StatusMap] = field(default_factory=dict)
    identities: Dict[str, Optional[dict]] = field(default_factory=dict)
    labels: Dict[str, Optional[str]] = field(default_factory=dict)


def snapshot_targets(manager: Any) -> Tuple[RemoteTarget, ...]:
    out = []
    for sid, backend in list(manager._registry.backends.items()):
        if is_remote_backend(backend) and backend.tmux_session:
            out.append(RemoteTarget(sid, backend.host, str(backend.tmux_session), backend))
    return tuple(out)


def host_status_map(host: Any, *, measure: bool = True) -> StatusMap:
    from src.core.session_backend import build_backend
    from src.core.tmux_listing import coerce_listing

    if not measure:
        cached = host.last_status_map
        return cached if isinstance(cached, StatusMap) else StatusMap(socket=host.socket)
    status_map = StatusMap(socket=host.socket)
    if host.is_up:
        try:
            probe = build_backend(None, session_id=_PROBE_SESSION_ID, working_dir=Path("/"),
                                  on_output=None, remote_host=host)
            listing = coerce_listing(probe.list_pane_status_all())
            if listing.ok:
                status_map = status_map_from_listing(listing, socket=host.socket)
            else:
                logger.info("remote_status_map_unavailable", host=host.host_key,
                            reason=listing.reason)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("remote_status_map_failed", host=host.host_key, error=str(exc))
    host.last_status_map = status_map
    return status_map


def gather_remote(targets: Sequence[RemoteTarget],
                  connect: Callable[[], Optional[sqlite3.Connection]], *,
                  measure: bool = True) -> RemoteGather:
    from src.core.session_label import label_for_name
    from src.core.session_store import identity_for_live_name

    gathered = RemoteGather()
    for target in targets:
        key = target.host.host_key
        if key not in gathered.maps:
            gathered.maps[key] = host_status_map(target.host, measure=measure)
    if not targets:
        return gathered
    try:
        conn = connect()
        if conn is None:
            return gathered
        with closing(conn):
            for target in targets:
                scope = dict(socket=target.host.socket, name=target.name,
                             host_key=target.host.host_key)
                gathered.identities[target.session_id] = identity_for_live_name(conn, **scope)
                gathered.labels[target.session_id] = label_for_name(conn, **scope)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("remote_listing_rows_unreadable", error=str(exc))
    return gathered


def gather_for(manager: Any) -> Callable[[Sequence[RemoteTarget]], RemoteGather]:
    return lambda targets: gather_remote(targets, manager._writable_datastore_connection)


def pane_liveness(status_map: Optional[StatusMap], backend: Any) -> Tuple[str, Optional[dict]]:
    """This remote session's liveness from its host's map, and its pane row. PURE.

    Description: a COMPLETE map from the backend's own socket decides both
      ways: named is alive (or a dead husk), absent is gone. Anything else
      (the host could not be asked) is ``unknown`` and never gone.
    Output: tuple[str, dict | None] - a ``LIVENESS_*`` value and the row.
    Example: pane_liveness(StatusMap({}, complete=True, socket='carnivore-remote'), b)[0]  # 'gone'
    """
    from src.core.session_status import resolve_listing_liveness

    name = backend.tmux_session
    if listing_proves_alive(status_map, name, backend_socket=backend.socket_name):
        row = status_map.get(name)
        return resolve_listing_liveness(True, row.get("status")), row
    measured = (status_map is not None and status_map.complete
                and status_map.socket == backend.socket_name)
    return resolve_listing_liveness(False if measured else None, None), None


def _family(sess: Any, identity: Optional[Mapping[str, Any]]) -> Tuple[Any, Optional[str], Any, Any]:
    from src.core.agent_family_display import resolve_family_for_display
    from src.core.agent_wrapper_display import resolve_wrapper_for_display
    from src.core.session_agent_evidence import choose_agent_evidence, recorded_launch_family
    from src.core.session_manager import _configured_wrappers

    row = identity or {}
    evidence = choose_agent_evidence(
        memory_agent_type=sess.agent_type, memory_from_fingerprint=sess.agent_type_via_fingerprint,
        row_agent_type=row.get("agent_type"), row_family_source=row.get("agent_family_source"))
    wrappers = _configured_wrappers()
    family, source = resolve_family_for_display(
        evidence.agent_type, wrappers, from_fingerprint=evidence.from_fingerprint,
        from_process=evidence.from_process)
    recorded = recorded_launch_family(
        row_agent_family=row.get("agent_family"), row_family_source=row.get("agent_family_source"),
        row_agent_type=row.get("agent_type"), effective_agent_type=evidence.agent_type)
    if recorded is not None:
        family, source = recorded
    wrapper = resolve_wrapper_for_display(evidence.agent_type, wrappers,
                                          from_fingerprint=evidence.from_fingerprint)
    return evidence.agent_type, family, source, wrapper


def _status(manager: Any, session_id: str, name: str, *, family: Optional[str], liveness: str,
            unread: bool, tmux_status: str) -> Tuple[str, str, Optional[str]]:
    from src.core.attention.display import activity_hint_for, status_source_for, to_display
    from src.core.listing_attention import attention_reads_for_name, resolve_row_status

    now = datetime.now(timezone.utc)
    watcher = manager._attention_watcher
    observation = watcher.observation_for(session_id, now=now) if watcher is not None else None
    if observation is not None:
        verdict = observation.verdict
        return (to_display(verdict, unread=unread, tmux_status=tmux_status),
                status_source_for(verdict),
                verdict.activity_hint or activity_hint_for(observation.evidence.registry))
    registry, transcript = attention_reads_for_name(
        name, registry_index={}, session_started_epoch=None, claude_session_uuid=None,
        working_dir=None, now=now)
    return resolve_row_status(registry=registry, transcript=transcript, tmux_liveness=liveness,
                              agent_family=family, pane=None, unread=unread,
                              tmux_status=tmux_status, now=now)


def remote_session_info(manager: Any, session_id: str,
                        gathered: Optional[RemoteGather] = None) -> Any:
    from src.core import unread_follow_up, unread_identity
    from src.core.session_startup_gate import GATE_UNKNOWN
    from src.core.session_status import (
        LIVENESS_GONE, LIVENESS_UNKNOWN, STATUS_UNKNOWN, derive_read_state)
    from src.core.sessions.remote_sessions import host_fields
    from src.models import SessionInfo, SessionStats, SessionStatus

    sess = manager._registry.sessions.get(session_id)
    backend = manager._registry.backends.get(session_id)
    if sess is None or not is_remote_backend(backend) or sess.status != SessionStatus.RUNNING:
        return None
    name = str(backend.tmux_session)
    if gathered is None or backend.host_key not in gathered.maps:
        gathered = gather_remote((RemoteTarget(session_id, backend.host, name, backend),),
                                 manager._writable_datastore_connection, measure=False)
    liveness, pane = pane_liveness(gathered.maps.get(backend.host_key), backend)
    if liveness == LIVENESS_GONE:
        return None
    tmux_status = pane["status"] if pane and liveness != LIVENESS_UNKNOWN else STATUS_UNKNOWN
    identity = gathered.identities.get(session_id)
    agent_type, family, family_source, wrapper = _family(sess, identity)
    family_name = family.name if family else None

    key = instance_name(backend)
    epoch = unread_identity.remember(
        manager._unread_epochs, key, unread_identity.epoch_of_row(pane)
    ) or unread_identity.resolve_epoch(manager._unread_epochs, key)
    unread = manager._is_unread(key, epoch, unread_follow_up.remember_row(
        manager._unread_rows, key, epoch, identity["id"] if identity else None))
    status, source, hint = _status(manager, session_id, name, family=family_name,
                                   liveness=liveness, unread=unread, tmux_status=tmux_status)
    uptime = int((datetime.utcnow() - sess.created_at).total_seconds())
    return SessionInfo(
        **host_fields(manager, backend),
        session=sess.model_copy(update={"pty_pid": None, "tmux_created_epoch": epoch}),
        recent_logs=manager.get_recent_logs(session_id=session_id),
        local_servers=[],
        stats=SessionStats(total_commands=manager._registry.command_count(session_id),
                           uptime_seconds=uptime,
                           log_lines=manager._registry.log_line_count(session_id),
                           local_servers=0),
        session_backend=backend.__class__.__name__.replace("Backend", "").lower(),
        tmux_session=name,
        label=gathered.labels.get(session_id),
        session_row_id=identity["id"] if identity else None,
        parent_session_id=identity["parent_session_id"] if identity else None,
        project_id=identity.get("project_id") if identity else None,
        project_name=identity.get("project_name") if identity else None,
        agent_type=agent_type,
        agent_family=family_name,
        agent_family_source=family_source,
        agent_wrapper_label=wrapper.label,
        pinned_theme=manager._theme_store.get_pin(key),
        activity_status=derive_read_state(status, unread=unread),
        status_source=source,
        activity_hint=hint,
        unread=unread,
        startup_gate=GATE_UNKNOWN,
        notifications_muted=manager.notification_policy_for(session_id).muted,
        created_by_cloude=True,
    )


async def reap_remote(manager: Any, targets: Sequence[RemoteTarget],
                      gathered: Optional[RemoteGather]) -> list:
    """Drop every remote registration its host's COMPLETE map does not name.

    Description: the per-host form of ``session_ghost_reap.reap_after_listing``
      and the same gate (complete map, same socket, and the same backend
      object holding the same name before and after the gather). A host
      that could not be asked has an incomplete map and reaps nothing.
      The row is not written.
    Inputs: manager; targets - the listing snapshot's, taken BEFORE the
      gather; gathered - that gather's result, or None (nothing remote).
    Output: list[str] - the session ids reaped.
    Example: await reap_remote(mgr, snapshot.remote_targets, gathered.remote)
    """
    from src.core.session_ghost_reap import RegistrationSnapshot, reap_after_listing

    reaped: list = []
    for host_key, status_map in (gathered.maps if gathered is not None else {}).items():
        mine = [RegistrationSnapshot(t.session_id, t.backend, t.name, t.backend.socket_name)
                for t in targets if t.host.host_key == host_key]
        if mine:
            reaped += await reap_after_listing(manager, mine, status_map)
            await asyncio.to_thread(reconcile_host_rows, manager, host_key,
                                    mine[0].socket, status_map)
    return reaped


def reconcile_host_rows(manager: Any, host_key: str, socket: str, status_map: Any) -> Any:
    from src.core.session_lifecycle import reconcile_from_listing
    from src.core.tmux_listing import TmuxListing

    if status_map is None or not status_map.complete or status_map.socket != socket:
        return None
    conn = manager._writable_datastore_connection()
    if conn is None:
        return None
    try:
        with closing(conn):
            if conn.execute("SELECT 1 FROM hosts WHERE key = ? AND kind = 'ssh'", (host_key,)).fetchone() is None:
                return None
            outcome = reconcile_from_listing(
                conn, listing=TmuxListing.answered(list(status_map.values())), socket=socket,
                host_key=host_key)
            if outcome.changed:
                conn.commit()
                logger.info("remote_lifecycle_reconciled", host=host_key,
                            stopped=len(outcome.stopped_uuids))
            return outcome
    except sqlite3.Error as exc:
        logger.warning("remote_lifecycle_reconcile_failed", host=host_key, error=str(exc))
        return None
