"""Which account a restart or recreate launches on, and remembering the choice.

THE RULE, in one place so the three launch paths cannot drift (respawn in
place, restart of a stopped row, recreate of a gone tmux session):

1. The restart dialog's choice (``requested``), when it sent one. It must be a
   claude account that can start and resume (``session_pin.require_launchable``)
   and the session must be a claude session; anything else is a
   :class:`~src.core.account_switch.session_pin.PinError` (an HTTP 400).
2. Otherwise the session's pinned account (``session_pin.pin_for``).
3. Otherwise None: the global active account, exactly as before this feature.

After a launch that worked, :func:`persist` applies the dialog's checkbox:
ticked saves or moves the pin, unticked clears it. A request with no account
(an older client, the unattended limit restart) never touches the pin.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.account_switch import session_pin
from src.core.account_switch.session_pin import PinError

ACCOUNT_FAMILY = "claude"


@dataclass(frozen=True)
class AccountPlan:

    account_id: Optional[str]
    chosen: bool = False
    pinned_box: bool = False
    persist: bool = True


NO_PLAN = AccountPlan(account_id=None)


def family_of(agent_type: Optional[str]) -> str:
    from src.config import settings
    from src.core.agent_families import resolve_agent_type

    return resolve_agent_type(agent_type, settings.load_auth_config().agents.wrappers)[0].name


def _resolve_blocking(
    config_path: Path, session_uuid: Optional[str], family: str,
    requested: Optional[str], pinned_box: bool, persist: bool = True,
) -> AccountPlan:
    if family != ACCOUNT_FAMILY:
        if requested:
            raise PinError("accounts can only be chosen for a claude session")
        return NO_PLAN
    if requested:
        session_pin.require_launchable(config_path, requested)
        return AccountPlan(requested, chosen=True, pinned_box=bool(pinned_box), persist=persist)
    return AccountPlan(session_pin.pin_for(config_path, session_uuid))


async def resolve(
    config_path: Path, *, session_uuid: Optional[str], family: str,
    requested: Optional[str] = None, pinned_box: bool = False, persist: bool = True,
) -> AccountPlan:
    return await asyncio.to_thread(
        _resolve_blocking, config_path, session_uuid, family, requested, pinned_box, persist)


async def persist(
    config_path: Path, session_uuid: Optional[str], plan: AccountPlan
) -> Optional[str]:
    if not plan.chosen or not plan.persist or plan.account_id is None or not session_uuid:
        return None
    return await asyncio.to_thread(
        session_pin.apply_choice, config_path, session_uuid, plan.account_id,
        pinned=plan.pinned_box)
