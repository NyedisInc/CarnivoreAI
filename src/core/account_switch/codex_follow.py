
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.account_switch import session_pin, store
from src.core.account_switch.active import find_account
from src.core.attention.codex_gather import DEFAULT_CODEX_HOME
from src.core.provider_ledger import accounts_store, relay_accounts
from src.core.provider_ledger.login_command import login_profile_dir

logger = structlog.get_logger()

AUTH_FILE = "auth.json"
CODE_CHOICE = "codex_account_choice"
CODE_NONE = "no_codex_account"

CREDENTIAL_FIELDS = ("OPENAI_API_KEY", "personal_access_token", "agent_identity", "bedrock_api_key", "bedrock_access_keys")


@dataclass(frozen=True)
class KeptHome:

    account_id: Optional[str]


class CodexAccountRefused(session_pin.PinError):

    def __init__(self, code: str, accounts: List[Dict[str, str]]) -> None:
        super().__init__(code)
        self.code = code
        self.accounts = accounts


def home_logged_in(home: str) -> bool:
    path = Path(os.path.expanduser(home)) / AUTH_FILE
    try:
        document: Any = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(document, dict):
        return False
    tokens = document.get("tokens")
    has_token = isinstance(tokens, dict) and bool(tokens.get("access_token"))
    return has_token or any(bool(document.get(field)) for field in CREDENTIAL_FIELDS)


def _logged_in_accounts(accounts: List[ProviderAccount]) -> List[ProviderAccount]:
    return [a for a in accounts if a.provider == "codex" and session_pin.is_launchable(a)
            and home_logged_in(profile_dir_for(a))]


def follow_active_account(config_path: Path) -> Optional[str]:
    accounts = session_pin.all_accounts(config_path)
    pointer = store.read_switch(config_path).active_for("codex")
    active = find_account(relay_accounts.with_relay(accounts_store.list_accounts(config_path)), pointer, "codex")
    if active is not None and session_pin.is_launchable(active):
        return active.id
    candidates = _logged_in_accounts(accounts)
    if len(candidates) == 1:
        return candidates[0].id
    if candidates:
        raise CodexAccountRefused(CODE_CHOICE, [{"id": a.id, "name": a.name} for a in candidates])
    if home_logged_in(DEFAULT_CODEX_HOME):
        return None
    raise CodexAccountRefused(CODE_NONE, [])


def _real(home: str) -> str:
    return os.path.realpath(os.path.expanduser(home))


def kept_home(config_path: Path, home: Optional[str]) -> Optional[KeptHome]:
    accounts = session_pin.all_accounts(config_path)
    pointer = store.read_switch(config_path).active_for("codex")
    if pointer is not None and find_account(accounts, pointer, "codex") is not None:
        return None
    target = _real(home or DEFAULT_CODEX_HOME)
    if not home_logged_in(target):
        return None
    if target == _real(DEFAULT_CODEX_HOME):
        return KeptHome(None)
    for account in accounts:
        if account.provider == "codex" and session_pin.is_launchable(account) and _real(login_profile_dir(account)) == target:
            return KeptHome(account.id)
    return None


def recorded_home(config_path: Path, launch_record: Optional[str]) -> Optional[KeptHome]:
    try:
        record: Any = json.loads(launch_record) if launch_record else {}
    except ValueError:
        record = {}
    account_block = record.get("account") if isinstance(record, dict) else None
    account_id = account_block.get("id") if isinstance(account_block, dict) else None
    if not isinstance(account_id, str) or not account_id:
        return kept_home(config_path, None)
    account = find_account(session_pin.all_accounts(config_path), account_id, "codex")
    return kept_home(config_path, login_profile_dir(account)) if account is not None else None
