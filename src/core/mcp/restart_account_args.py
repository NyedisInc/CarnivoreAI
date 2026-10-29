
from __future__ import annotations

import asyncio
from typing import Any, Optional

from src.core.mcp.common import ToolError

PROPERTIES = {
    "account": {"type": "string", "maxLength": 200,
                "description": "A claude account id from launch_accounts_list; the agent resumes on it instead of its saved or the active account. This computer's sessions only."},
    "always_use_account": {"type": "boolean",
                           "description": "With account: save it as this agent's account (later restarts and wakes use it)."},
}


def read(args: dict) -> tuple[Optional[str], bool]:
    account = args.get("account")
    if "account" in args and (not isinstance(account, str) or not account.strip() or len(account) > 200):
        raise ToolError("account must be a claude account id (see launch_accounts_list)")
    pin = args.get("always_use_account", False)
    if not isinstance(pin, bool):
        raise ToolError("always_use_account must be true or false")
    if pin and account is None:
        raise ToolError("always_use_account needs account")
    return account, pin


async def refuse_bad(account: Optional[str], pin: bool, agent_type: Optional[str], *, remote: bool = False) -> None:
    from src.core.account_switch import create_account, session_pin
    from src.core.account_switch.launch_env import _config_path

    if account is None:
        return
    try:
        await create_account.plan_for_create(
            account_id=account, account_pinned=pin, agent_type=agent_type, is_peer=False, is_local=not remote)
    except create_account.CreateAccountRefused as exc:
        try:
            ids = [a.id for a in await asyncio.to_thread(session_pin.launchable_accounts, _config_path())]
        except (FileNotFoundError, ValueError, OSError):
            ids = []
        raise ToolError(f"{exc}; launchable account ids: {', '.join(ids) or 'none'}") from exc


def shown(account: Optional[str], pin: bool) -> str:
    return f" on account {account}{' (always)' if pin else ''}" if account else ""
