
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

import structlog

from src.core.unread_store import UnreadStore

logger = structlog.get_logger()

RowMemo = MutableMapping[str, int]


def _instance_key(tmux_name: Optional[str], epoch: Any) -> Optional[str]:
    if not tmux_name or epoch is None:
        return None
    try:
        return UnreadStore.compose_key(tmux_name, epoch)
    except (TypeError, ValueError):
        return None


def remember_row(
    memo: RowMemo,
    tmux_name: Optional[str],
    epoch: Optional[int],
    row_id: Optional[int],
) -> Optional[int]:
    key = _instance_key(tmux_name, epoch)
    if key is not None and row_id is not None:
        memo[key] = int(row_id)
    return row_id


def row_id_for(manager: Any, tmux_name: Optional[str], epoch: Optional[int]) -> Optional[int]:
    if not tmux_name:
        return None
    memo: Optional[RowMemo] = getattr(manager, "_unread_rows", None)
    if memo is None:
        memo = {}
    key = _instance_key(tmux_name, epoch)
    if key is not None:
        cached = memo.get(key)
        if cached is not None:
            return cached
        reader = getattr(manager, "_identity_for_instance", None)
        identity = reader(tmux_name, epoch) if callable(reader) else None
        found = identity.get("id") if identity else None
        return remember_row(memo, tmux_name, epoch, found)
    reader = getattr(manager, "_identity_for_live_name", None)
    identity = reader(tmux_name) if callable(reader) else None
    return identity.get("id") if identity else None


def is_unread(
    manager: Any,
    tmux_name: Optional[str],
    epoch: Optional[int],
    row_id: Optional[int] = None,
) -> bool:
    memo = getattr(manager, "_unread_rows", None)
    key = _instance_key(tmux_name, epoch)
    if row_id is None and memo and key is not None:
        row_id = memo.get(key)
    return manager._unread_store.is_unread(tmux_name, epoch, row_id=row_id)


def mark(manager: Any, tmux_name: str) -> None:
    epoch = manager._unread_epoch(tmux_name)
    row_id = row_id_for(manager, tmux_name, epoch)
    manager._unread_store.set_follow_up(row_id, tmux_name, epoch)
    logger.debug("unread_follow_up_marked", tmux_name=tmux_name,
                 epoch=epoch, row_id=row_id)


def clear(manager: Any, tmux_name: str) -> None:
    epoch = manager._unread_epoch(tmux_name)
    manager._unread_store.clear(
        tmux_name, epoch, row_id=row_id_for(manager, tmux_name, epoch)
    )


def asleep_flag(store: Optional[UnreadStore], row: Mapping[str, Any]) -> Optional[bool]:
    if store is None:
        return None
    return store.is_followed_up(
        row.get("id"), row.get("tmux_name"), row.get("tmux_created_epoch")
    )


def carry_into_sleep(manager: Any, row: Mapping[str, Any]) -> bool:
    store = getattr(manager, "_unread_store", None)
    if store is None:
        return False
    moved = store.carry_unread_into_row(
        row.get("id"), row.get("tmux_name"), row.get("tmux_created_epoch")
    )
    if moved:
        logger.info("unread_follow_up_carried_into_sleep",
                    row_id=row.get("id"), tmux_name=row.get("tmux_name"))
    return moved
