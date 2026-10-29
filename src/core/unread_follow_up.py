
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
    """The ``sessions.id`` a follow-up flag for this session keys on.

    Description: the memo first; then the exact instance read; and only
      when the epoch could not be measured (the pane is not on the socket,
      which is what an ASLEEP session is) the newest row carrying the name,
      which while a session sleeps is its own row, because the name stays
      reserved for it (``session_sleep.reserved_names``). Used by the two
      rare user actions (mark, clear), never by a per-poll reader.
    Inputs: manager (SessionManager). tmux_name (str | None). epoch (int |
      None).
    Output: int | None - None when no row is recorded for this session (a
      truly external tmux session), which falls back to the instance key.
    Example: row_id_for(mgr, 'cloude_a', 17)  # 4
    """
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
    """Before a sleep closes the pane, move its unread mark onto the row.

    Description: the mark lives on the instance key and would go with the
      pane (and be pruned at boot, and not be found by the wake's NEW
      instance). Both halves move: the manual reminder (a flag set while
      the row could not be read, or before this build) and the automatic
      turn-end mark, so a session that finished unread and was slept by
      the timer (or the user) is still unread on its asleep row and after
      its wake. Never raises: the sleep must not fail over a reminder.
    Inputs: manager (SessionManager). row (Mapping) - the row being slept,
      read before the close.
    Output: bool - True when a mark was moved.
    Example: carry_into_sleep(mgr, row)  # False when nothing was flagged
    """
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
