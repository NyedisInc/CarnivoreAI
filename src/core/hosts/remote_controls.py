
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from src.core.hosts.identity import (
    REMOTE_ID_PREFIX,
    instance_name,
    is_remote_backend,
    parse_remote_session_id,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class RemoteRef:

    session_id: str
    backend: Any
    key: str


def resolve_remote(manager: Any, value: Optional[str]) -> Optional[RemoteRef]:
    backends = getattr(getattr(manager, "_registry", None), "backends", None) or {}
    backend = backends.get(value) if value else None
    if is_remote_backend(backend):
        return RemoteRef(str(value), backend, str(instance_name(backend)))
    parsed = parse_remote_session_id(value)
    if parsed is None:
        return None
    host_key, name = parsed
    for sid, candidate in list(backends.items()):
        if is_remote_backend(candidate) and candidate.host_key == host_key \
                and candidate.tmux_session == name:
            return RemoteRef(sid, candidate, str(value))
    raise LookupError(f"no session named {name!r} is registered on host {host_key}")


def set_label(manager: Any, ref: RemoteRef, label: str) -> bool:
    from src.core.db import transaction
    from src.core.session_label import set_label_for_instance

    epoch = manager._instance_epochs.get(ref.session_id)
    backend = ref.backend
    try:
        conn = manager._writable_datastore_connection()
        if conn is None:
            return False
        with closing(conn), transaction(conn):
            return set_label_for_instance(conn, socket=backend.socket_name,
                                          name=str(backend.tmux_session), epoch=epoch,
                                          label=label, host_key=backend.host_key)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("remote_label_write_failed", host=backend.host_key, error=str(exc))
        return False


def set_pin(manager: Any, ref: RemoteRef, theme_id: Optional[str]) -> None:
    if not manager._theme_store.set_pin(ref.key, theme_id):
        return
    sess = manager._registry.sessions.get(ref.session_id)
    if sess is not None:
        sess.pinned_theme = theme_id or None


def image_file_stem(key: str) -> str:
    if not key.startswith(REMOTE_ID_PREFIX):
        return key
    return "remote-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
