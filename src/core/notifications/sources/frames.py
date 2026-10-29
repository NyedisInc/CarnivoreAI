
from __future__ import annotations

from typing import Any, Mapping, Optional

from src.core.notifications import contracts
from src.core.notifications.sources import common


def auto_slept(session_id: str, session_uuid: str, name: Optional[str], info: Any) -> None:
    """Emit ``session.auto_slept``. ``info`` is the SessionInfo read before the sleep (None when unreadable).

    Inputs: session_id, session_uuid (str); name (display name | None); info (SessionInfo | None, for the
    tmux name and project, which the registry no longer holds once the session sleeps).
    """
    contracts.emit(contracts.NotifyEvent(
        type_id="session.auto_slept", kind="session.auto_slept", title=common.type_title("session.auto_slept"),
        ts=common.now(), instance_key=f"auto_slept:{session_uuid}:{common.now():.0f}", session_id=session_id,
        tmux_name=getattr(info, "tmux_session", None), project=getattr(info, "project_name", None) or "",
        session_ref=name or "", session_uuid=session_uuid or None,
    ))


def limit_rotation(
    outcome: str, *, session: str, from_account_id: str, to_account_id: str, limit_kind: str,
    from_name: str = "", to_name: str = "",
) -> None:
    limit = {"weekly_model": "weekly model", "other": ""}.get(limit_kind, limit_kind)
    contracts.emit(contracts.NotifyEvent(
        type_id="session.limit_rotation", kind="provider_account.switched", title=common.type_title("session.limit_rotation"),
        ts=common.now(), instance_key=f"limit_rotation:{outcome}:{session}:{common.now():.0f}", session_ref=session,
        copy_variant=outcome,
        copy_fields=(("from_account", from_name or from_account_id), ("to_account", to_name or to_account_id), ("limit", limit)),
        details=f"{from_account_id} to {to_account_id}, {limit_kind} limit",
    ))


def account_switched(entry: Mapping[str, Any]) -> None:
    contracts.emit(contracts.NotifyEvent(
        type_id="account.switched", kind="provider_account.switched", title=common.type_title("account.switched"),
        ts=common.now(), instance_key=f"account_switched:{entry.get('to_account_id')}:{entry.get('at')}",
    ))
