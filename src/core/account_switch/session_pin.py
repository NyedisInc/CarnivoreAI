
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core import config_writer
from src.core.account_switch import auto_switch, shared_links
from src.core.account_switch.active import PROVIDERS, find_account
from src.core.provider_ledger import accounts_store, poller_scan

logger = structlog.get_logger()

PINS_KEY = "session_account_pins"

_ID_SHAPE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

PIN_PROVIDER = PROVIDERS[0]


class PinError(ValueError):
    pass


def read_pins(config: Dict[str, Any]) -> Dict[str, str]:
    block = config.get(PINS_KEY)
    if not isinstance(block, dict):
        return {}
    return {
        str(k): v for k, v in block.items()
        if isinstance(v, str) and _ID_SHAPE.fullmatch(v)
    }


def pin_for(config_path: Path, session_uuid: Optional[str]) -> Optional[str]:
    if not session_uuid:
        return None
    try:
        return read_pins(config_writer.read_config(config_path)).get(session_uuid)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("session_account_pin_unreadable", error=type(exc).__name__)
        return None


def _write(config_path: Path, session_uuid: str, account_id: Optional[str]) -> bool:

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pins = dict(config.get(PINS_KEY) or {}) if isinstance(config.get(PINS_KEY), dict) else {}
        if pins.get(session_uuid) == account_id:
            return None
        if account_id is None:
            if session_uuid not in pins:
                return None
            pins.pop(session_uuid)
        else:
            pins[session_uuid] = account_id
        return {**config, PINS_KEY: pins}

    return bool(config_writer.commit(Path(config_path).expanduser(), mutate).wrote)


def carry(config_path: Path, session_uuid: str, account_id: str) -> bool:
    if not _ID_SHAPE.fullmatch(account_id) or pin_for(config_path, session_uuid):
        return False
    try:
        return _write(config_path, session_uuid, account_id)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("session_account_pin_carry_failed", error=type(exc).__name__)
        return False


def apply_choice(
    config_path: Path, session_uuid: str, account_id: str, *, pinned: bool
) -> str:
    if not _ID_SHAPE.fullmatch(account_id):
        raise PinError("an account id is a lowercase slug")
    changed = _write(config_path, session_uuid, account_id if pinned else None)
    if not changed:
        return "unchanged"
    logger.info("session_account_pin_changed", session_uuid=session_uuid,
                account_id=account_id if pinned else None, pinned=pinned)
    return "pinned" if pinned else "cleared"


def all_accounts(config_path: Path) -> List[ProviderAccount]:
    return poller_scan.with_auto_default(accounts_store.list_accounts(config_path))


def is_launchable(account: Optional[ProviderAccount]) -> bool:
    if account is None or account.provider != PIN_PROVIDER:
        return False
    default = shared_links.is_default_profile(account.provider, profile_dir_for(account))
    if not default and not account.managed:
        return False
    return auto_switch._linkable(account)


def launchable_accounts(config_path: Path) -> List[ProviderAccount]:
    return [a for a in all_accounts(config_path) if is_launchable(a)]


def require_launchable(config_path: Path, account_id: str) -> ProviderAccount:
    account = find_account(all_accounts(config_path), account_id, PIN_PROVIDER)
    if account is None or not is_launchable(account):
        raise PinError("that account cannot start and resume this session")
    return account
