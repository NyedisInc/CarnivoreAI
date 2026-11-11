
from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from src.config import settings
from src.config.provider_account_switch import pointer_field
from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR, DEFAULT_CODEX_HOME, ProviderAccount, profile_dir_for
from src.core.account_switch import active as active_mod, profile_setup, shared_links, store
from src.core.pack.relay import codex_target, target_side
from src.core.provider_ledger import accounts_store, codex_credentials, credentials, poller_scan, relay_accounts

logger = structlog.get_logger()


def _own_login_present(provider: str) -> bool:
    if provider == "codex":
        return codex_credentials.read_codex_credential(DEFAULT_CODEX_HOME) is not None
    return credentials.read_claude_credential(DEFAULT_CLAUDE_CONFIG_DIR) is not None


def adopt(provider: str, account_key: str, sender_install_id: str) -> bool:
    path = Path(settings.auth_config_file).expanduser()
    try:
        before = store.read_switch(path)
        configured = accounts_store.list_accounts(path)
    except (OSError, ValueError, FileNotFoundError):
        return False
    accounts = relay_accounts.with_relay(poller_scan.with_auto_default(configured))
    if active_mod.find_account(accounts, before.active_for(provider), provider) is not None or _own_login_present(provider):
        return False
    name = (codex_target.codex_relay_profile_name if provider == "codex" else target_side.relay_profile_name)(account_key, sender_install_id)
    account: Optional[ProviderAccount] = next((a for a in accounts if a.id == name and a.provider == provider), None)
    if account is None:
        return False
    if provider == "claude":
        if not profile_setup.setup_done(account):
            return False
        shared_links.ensure_shared_links(profile_dir_for(account), "claude", managed=True)
    store.set_active(path, provider, active_mod.pointer_for(account), expect={pointer_field(provider): None})
    logger.info("pack_relay_adopted_for_new_sessions", provider=provider, account=account_key)
    return True

