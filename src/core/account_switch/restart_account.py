
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.account_switch import session_pin
from src.core.account_switch.session_pin import PinError

ACCOUNT_FAMILY = "claude"
ACCOUNT_FAMILIES = ("claude", "codex")


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
    if family not in ACCOUNT_FAMILIES:
        if requested:
            raise PinError("accounts can only be chosen for a claude or codex session")
        return NO_PLAN
    if requested:
        session_pin.require_launchable(config_path, requested, family)
        return AccountPlan(requested, chosen=True, pinned_box=bool(pinned_box), persist=persist)
    pinned = session_pin.pin_for(config_path, session_uuid)
    return AccountPlan(pinned if pinned and session_pin.pin_fits(config_path, pinned, family) else None)


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
