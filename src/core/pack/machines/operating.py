
from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.pack.machines import capabilities, settings_doc
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.meshdata import envelope, ops_kind
from src.core.relay_identity.device_key import DeviceKeyUnavailable

log = structlog.get_logger(__name__)

CURRENT: Dict[str, Any] = {}
_DIGEST: Optional[str] = None
_LOCK = threading.Lock()
EDIT_LOCK = threading.Lock()


def _active() -> Any:
    from src.core.pack.meshdata import gossip

    return gossip.ACTIVE


def refresh(store: Any, lst: Any) -> bool:
    global CURRENT, _DIGEST
    with _LOCK:
        digest = store.kind_digest(lst, ops_kind.KIND)
        if digest == _DIGEST:
            return False
        rows = store.kind_rows(lst, ops_kind.KIND)
        fresh = {k: v for k, (v, _stamp) in rows.items() if ops_kind.valid(k, v)}
        _DIGEST = digest
        changed = fresh != CURRENT
        CURRENT = fresh
        return changed


def effective(doc: settings_doc.PackSettings) -> settings_doc.PackSettings:
    current = CURRENT
    active = _active()
    if not current or not capabilities.mesh_on() or active is None:
        return doc
    try:
        lst = active.held_list()
    except (OSError, ValueError, sqlite3.Error) as exc:
        log.debug("mesh_ops_effective_unreadable", error_type=type(exc).__name__)
        return doc
    if not isinstance(lst, RosterV2) or not _alpha_speaks_mesh(lst, active.store.own_iid):
        return doc
    try:
        return settings_doc.PackSettings(**{**doc.model_dump(), **current})
    except ValueError as exc:
        log.debug("mesh_ops_effective_invalid", error_type=type(exc).__name__)
        return doc


def _alpha_speaks_mesh(lst: RosterV2, own_iid: str) -> bool:
    if lst.alpha == own_iid:
        return True
    entry = lst.entry(lst.alpha)
    if entry is None or not capabilities.has(entry.capabilities, capabilities.CAP_MESH):
        return False
    from src.core.federation import peer_links

    links = peer_links.LINKS
    if links is not None and links.client(lst.alpha) is not None and not capabilities.has(links.capabilities(lst.alpha), capabilities.CAP_MESH):
        return False
    return True


def may_write(own_iid: str) -> bool:
    if not capabilities.mesh_on():
        return False
    active = _active()
    if active is None:
        return False
    try:
        lst = active.held_list()
        return isinstance(lst, RosterV2) and ops_kind.origin_ok(lst, own_iid) and _alpha_speaks_mesh(lst, own_iid)
    except (OSError, ValueError, sqlite3.Error) as exc:
        log.warning("mesh_ops_gate_failed", error=type(exc).__name__)
        return False


def write_own(changes: Dict[str, Any]) -> int:
    from src.core.pack.meshdata import gossip

    active = _active()
    if active is None:
        return 0
    if envelope.own_kid(active.signing) is None:
        raise DeviceKeyUnavailable("the federation key could not be read")
    gen = active.store.generation
    lst = active.held_list()
    items = [(k, v, None) for k, v in changes.items() if k in ops_kind.KEYS]
    written, _refused = active.store.put_many(ops_kind.KIND, items, active.signing, lst, gen=gen)
    refresh(active.store, lst)
    gossip.wake()
    return written


def edit(runtime: Any, changes: Dict[str, Any]) -> settings_doc.PackSettings:
    with EDIT_LOCK:
        return runtime.edit_settings(changes)


def missing(changes: Dict[str, Any]) -> List[str]:
    keys = sorted(k for k in changes if k in ops_kind.KEYS)
    active = _active()
    if active is None:
        return keys
    try:
        rows = active.store.kind_rows(active.held_list(), ops_kind.KIND)
    except (OSError, ValueError, sqlite3.Error) as exc:
        log.debug("mesh_ops_missing_unreadable", error_type=type(exc).__name__)
        return keys
    return [k for k in keys if k not in rows or rows[k][0] != changes[k]]


def records_expected(runtime: Any, own_iid: str) -> bool:
    if not capabilities.mesh_on():
        return False
    try:
        lst = runtime.held_list()
    except (OSError, ValueError, sqlite3.Error) as exc:
        log.debug("mesh_ops_records_expected_unreadable", error_type=type(exc).__name__)
        return True
    return isinstance(lst, RosterV2) and ops_kind.origin_ok(lst, own_iid)


def forget_pack(own_iid: str) -> None:
    global CURRENT, _DIGEST
    from src.core.pack.meshdata import gossip

    with _LOCK:
        gossip.forget_pack(own_iid)
        CURRENT = {}
        _DIGEST = None


def _project(runtime: Any) -> None:
    if not CURRENT:
        return
    own = runtime.install_id
    with EDIT_LOCK:
        current = CURRENT
        if not current or runtime.content_alpha() != own or runtime.settings().master_install_id != own:
            return
        doc = runtime.settings().model_dump(mode="json")
        diff = {k: v for k, v in current.items() if doc.get(k) != v}
        if not diff:
            return
        try:
            runtime.edit_settings(diff)
        except (DeviceKeyUnavailable, ValueError, OSError) as exc:
            log.warning("mesh_ops_project_failed", error=type(exc).__name__)
            return
    log.info("mesh_ops_projected", fields=sorted(diff))


def _ingest(runtime: Any, store: Any, lst: Any) -> None:
    if refresh(store, lst):
        runtime.settings_changed()
    _project(runtime)


def step(runtime: Any) -> Callable[[Any, Any], Awaitable[None]]:
    async def run(service: Any, lst: Any) -> None:
        await asyncio.to_thread(_ingest, runtime, service.store, lst)

    return run
