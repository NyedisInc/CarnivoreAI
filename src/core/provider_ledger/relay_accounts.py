
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.claude_config import profile_roots
from src.models.provider_ledger import AccountUsage

RELAY_NAME_RE = re.compile(r"([0-9a-f]{12})-([a-z0-9][a-z0-9-]{0,62})-relay")
CODEX_RELAY_NAME_RE = re.compile(r"([0-9a-f]{12})-([a-z0-9][a-z0-9-]{0,62})-relay-codex")
NAME_SUFFIX = " (relayed)"


def is_relay_account(account: Optional[ProviderAccount]) -> bool:
    return account is not None and account.provider == "claude" and account.managed and RELAY_NAME_RE.fullmatch(account.id) is not None


def is_codex_relay_account(account: Optional[ProviderAccount]) -> bool:
    return (account is not None and account.provider == "codex" and account.managed
            and CODEX_RELAY_NAME_RE.fullmatch(account.id) is not None)


def account_key_of(account: ProviderAccount) -> str:
    match = RELAY_NAME_RE.fullmatch(account.id)
    return match.group(2) if match else account.id


def relay_accounts() -> List[ProviderAccount]:
    out: List[ProviderAccount] = []
    for folder in profile_roots._relay_profile_dirs():
        match = RELAY_NAME_RE.fullmatch(folder.name)
        if match:
            out.append(ProviderAccount(id=folder.name, name=match.group(2) + NAME_SUFFIX, provider="claude", managed=True))
    return out


def _codex_relay_dirs() -> List[Path]:
    override = os.environ.get(profile_roots.ACCOUNTS_DIR_ENV, "").strip()
    root = Path(override).expanduser() if override else Path.home() / ".carnivore" / "accounts"
    try:
        return sorted(p for p in root.glob("????????????-*-relay-codex") if p.is_dir() and CODEX_RELAY_NAME_RE.fullmatch(p.name))
    except OSError:
        return []


def codex_relay_accounts() -> List[ProviderAccount]:
    return [ProviderAccount(id=f.name, name=CODEX_RELAY_NAME_RE.fullmatch(f.name).group(2) + NAME_SUFFIX, provider="codex", managed=True)
            for f in _codex_relay_dirs()]


def codex_relay_rows(now: Optional[datetime] = None) -> List[AccountUsage]:
    from src.core.provider_ledger import codex_credentials, credentials

    from src.core.pack.relay import ledger_sync_store, ledger_sync_view

    clock = now or datetime.now(timezone.utc)
    rows: List[AccountUsage] = []
    stored, names = ledger_sync_store.statuses_by_profile(), ledger_sync_view.directory()
    for folder in _codex_relay_dirs():
        match = CODEX_RELAY_NAME_RE.fullmatch(folder.name)
        credential = codex_credentials.read_codex_credential(str(folder))
        rows.append(ledger_sync_view.fill_relayed(AccountUsage(
            id=folder.name, name=match.group(2) + NAME_SUFFIX, provider="codex",
            credential_state=credentials.credential_state_for(credential, clock), plan=credential.plan if credential else None,
            managed=True, setup_complete=True, relayed=True, relay_expires_at=credential.expires_at if credential else None),
            stored.get(folder.name), names))
    return rows


def with_relay(accounts: List[ProviderAccount]) -> List[ProviderAccount]:
    have = {a.id for a in accounts}
    extra = [a for a in [*relay_accounts(), *codex_relay_accounts()] if a.id not in have]
    return [*accounts, *extra] if extra else accounts


def setup_complete(account: ProviderAccount) -> bool:
    from src.core import config_writer
    from src.core.provider_ledger.credentials import claude_identity_path

    try:
        return config_writer.read_config(claude_identity_path(profile_dir_for(account))).get("hasCompletedOnboarding") is True
    except (OSError, UnicodeDecodeError, ValueError):
        return False


def relay_rows(now: Optional[datetime] = None) -> List[AccountUsage]:
    from src.core.pack.relay import ledger_sync_store, ledger_sync_view
    from src.core.provider_ledger import credentials

    clock = now or datetime.now(timezone.utc)
    rows: List[AccountUsage] = []
    stored, names = ledger_sync_store.statuses_by_profile(), ledger_sync_view.directory()
    for account in relay_accounts():
        credential = credentials.read_claude_credential(profile_dir_for(account))
        rows.append(ledger_sync_view.fill_relayed(AccountUsage(
            id=account.id, name=account.name, provider="claude", credential_state=credentials.credential_state_for(credential, clock),
            plan=credential.subscription_type if credential else None, managed=True, setup_complete=setup_complete(account),
            relayed=True, relay_expires_at=credential.expires_at if credential else None),
            stored.get(account.id), names))
    return rows


def all_relay_rows(now: Optional[datetime] = None) -> List[AccountUsage]:
    return [*relay_rows(now), *codex_relay_rows(now)]
