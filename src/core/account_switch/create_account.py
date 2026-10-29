
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Optional

import structlog

from src.core.account_switch import restart_account
from src.core.account_switch.launch_env import _config_path
from src.core.account_switch.session_pin import PinError

logger = structlog.get_logger()


class CreateAccountRefused(ValueError):
    pass


async def plan_for_create(
    *, account_id: Optional[str], account_pinned: bool, agent_type: Optional[str], is_peer: bool, is_local: bool,
    auto_start_claude: bool = True,
) -> restart_account.AccountPlan:
    if not account_id:
        if account_pinned:
            raise CreateAccountRefused("account_pinned needs an account_id")
        return restart_account.NO_PLAN
    if is_peer or not is_local:
        raise CreateAccountRefused("an account is chosen on the computer that runs the session")
    if not auto_start_claude:
        raise CreateAccountRefused("accounts can only be chosen for a claude session")
    try:
        return await restart_account.resolve(
            _config_path(), session_uuid=None, family=restart_account.family_of(agent_type),
            requested=account_id, pinned_box=account_pinned)
    except PinError as exc:
        raise CreateAccountRefused(str(exc)) from exc


async def pin_after_create(manager: Any, tmux_name: Optional[str], plan: restart_account.AccountPlan) -> Optional[str]:
    if not (plan.chosen and plan.pinned_box and plan.account_id):
        return None
    try:
        identity = await asyncio.to_thread(
            manager._row_identity_for_tmux_name, tmux_name, manager.tmux_socket_name()) if tmux_name else {}
        result = await restart_account.persist(_config_path(), identity.get("session_uuid"), plan)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, PinError) as exc:
        logger.warning("session_account_pin_not_saved", tmux_name=tmux_name, account_id=plan.account_id,
                       error=type(exc).__name__)
        return None
    if result is None:
        logger.warning("session_account_pin_not_saved", tmux_name=tmux_name, account_id=plan.account_id)
    return result
