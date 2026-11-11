
from __future__ import annotations

import asyncio
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

from src.core.db import DatastoreError, connect, db_path_for
from src.core.plugin_health.presence import GONE, UNREADABLE, folder_presence
from src.core.skills import kinds
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem
from src.cplugs.host import identity, install_folder, sideload, sideload_git
from src.cplugs.host import state as owner_state

logger = structlog.get_logger()

PRUNE_ERRORS = (OSError, sqlite3.Error, DatastoreError, identity.LedgerUnreadable, sideload.SideloadRefused)
_BUILTIN_SOURCE = "builtin"


def installed(live: Any) -> List[InstalledItem]:
    return [r for r in live.installed_rows() if r.kind == kinds.KIND_CPLUG and r.source_index_url != _BUILTIN_SOURCE and "/" in r.item_id]


def folder_states(live: Any) -> Dict[str, str]:
    return {r.item_id: folder_presence(install_folder.deciding_folder(live.state_dir, r.item_id)) for r in installed(live)}


def _now_stamp() -> str:
    return datetime.fromtimestamp(sideload.wall(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _drop_stores(state_dir: Path, item_id: str) -> Optional[Dict[str, str]]:
    name = item_id.partition("/")[2]
    local = sideload.is_local(item_id)
    conn = connect(db_path_for(state_dir), create=False)
    try:
        ledger = InstallLedger(conn)
        row = ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
        if row is None:
            return None
        try:
            held = identity.lookup(state_dir, name)
            if held is None or not identity.mark_removed(state_dir, name, version=row.version, publisher_key_id=row.publisher_key_id,
                                                        removed_at=_now_stamp()):
                logger.warning("plugin_prune_skipped", plugin=name, reason="no_install_record")
                return None
        except (identity.LedgerUnreadable, owner_state.StateWriteFailed) as exc:
            logger.error("plugin_prune_skipped", plugin=name, reason="install_ledger_unusable", error_type=type(exc).__name__)
            return None
        ledger.delete(row.install_id)
    finally:
        conn.close()
    if local:
        sideload.forget(state_dir, name)
        sideload_git.forget(state_dir, name)
        shutil.rmtree(sideload.code_root_of(state_dir, name), ignore_errors=True)
    _park_owner_state(state_dir, name, drop=local)
    return {"name": name, "uuid": held.uuid, "folder": str(identity.data_dir(state_dir, held.uuid))}


def _park_owner_state(state_dir: Path, name: str, *, drop: bool) -> None:
    try:
        if drop:
            owner_state.forget(state_dir, name)
        else:
            owner_state.switch_off(state_dir, name)
    except owner_state.StateWriteFailed as exc:
        logger.warning("plugin_prune_state_not_saved", plugin=name, error_type=type(exc).__name__)


async def prune_gone_install(live: Any, item_id: str) -> bool:
    name = item_id.partition("/")[2]
    state_dir = Path(live.state_dir)
    try:
        return await _prune_measured_gone(live, item_id, name, state_dir)
    except PRUNE_ERRORS as exc:
        logger.error("plugin_prune_failed", plugin=name, error_type=type(exc).__name__, error=str(exc))
        return False


async def _prune_measured_gone(live: Any, item_id: str, name: str, state_dir: Path) -> bool:
    if await asyncio.to_thread(folder_presence, install_folder.deciding_folder(state_dir, item_id)) != GONE:
        return False
    await live.supervisor.disable(name, "folder_gone")
    await asyncio.to_thread(live.effects.cancel, name)
    live.supervisor.forget(name)
    dropped = await asyncio.to_thread(_drop_stores, state_dir, item_id)
    if dropped is None:
        return False
    await asyncio.to_thread(live.load_registry)
    await asyncio.to_thread(live.resolve_alerts, name)
    live.removed_notice(name, data_folder=dropped["folder"], sideload=sideload.is_local(item_id))
    live.host.publish("cplugs")
    logger.info("plugin_pruned_folder_gone", plugin=name, source="folder" if sideload.is_local(item_id) else "catalog")
    return True


async def prune_pass(live: Any, only: Optional[Set[str]] = None) -> List[str]:
    try:
        states = await asyncio.to_thread(folder_states, live)
    except PRUNE_ERRORS as exc:
        logger.error("plugin_prune_pass_failed", error_type=type(exc).__name__, error=str(exc))
        return []
    pruned: List[str] = []
    for item_id, presence in sorted(states.items()):
        if only is not None and item_id not in only:
            continue
        if presence == UNREADABLE:
            logger.warning("plugin_folder_unreadable", plugin=item_id.partition("/")[2])
        elif presence == GONE and await prune_gone_install(live, item_id):
            pruned.append(item_id)
    return pruned
