
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR, profile_dir_for
from src.core.account_switch import session_pin, store
from src.core.account_switch.active import effective_active, find_account
from src.core.pack.relay import target_side
from src.core.provider_ledger.credentials import read_claude_identity

logger = structlog.get_logger()
PROVIDER = "claude"
NOT_USABLE_CODE = "account_not_usable"
NOT_USABLE_DETAIL = "no login on this computer can run that session's Claude account; log in here or relay the account first"


def session_account_key(config_path: Path, session_uuid: str) -> Optional[str]:
    pinned = session_pin.pin_for(config_path, session_uuid)
    if pinned:
        return pinned
    try:
        return effective_active(session_pin.all_accounts(config_path), store.read_switch(config_path), PROVIDER).account_id
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("pack_move_account_unreadable", error=type(exc).__name__)
        return None


def session_profile_dir(config_path: Path, session_uuid: str) -> Optional[str]:
    key = session_account_key(config_path, session_uuid)
    if not key:
        return None
    try:
        found = find_account(session_pin.all_accounts(config_path), key, PROVIDER)
    except (FileNotFoundError, ValueError, OSError):
        return ""
    return profile_dir_for(found) if found is not None else ""


def launch_for(account_key: Optional[str], sender_install_id: Optional[str], config_path: Path) -> Optional[Dict[str, Any]]:
    if account_key:
        profile = target_side.relay_profile_dir(account_key, sender_install_id) if sender_install_id else target_side.find_relay_profile(account_key)
        if profile and Path(profile).is_dir():
            return {"account_id": None, "extra_env": {"CLAUDE_CONFIG_DIR": profile}}
        try:
            account = find_account(session_pin.all_accounts(config_path), account_key, PROVIDER)
        except (FileNotFoundError, ValueError, OSError):
            return None
        if account is not None and session_pin.is_launchable(account) and read_claude_identity(profile_dir_for(account)) is not None:
            return {"account_id": account_key, "extra_env": None}
        return None
    return {"account_id": None, "extra_env": None} if read_claude_identity(DEFAULT_CLAUDE_CONFIG_DIR) is not None else None


def launch_for_session(config_path: Path, session_uuid: str) -> Optional[Dict[str, Any]]:
    key = session_pin.pin_for(config_path, session_uuid)
    return launch_for(key, None, config_path) if key else {"account_id": None, "extra_env": None}
