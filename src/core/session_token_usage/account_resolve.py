
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.provider_ledger import accounts_store, poller, poller_scan
from src.core.provider_ledger.default_login import (
    accounts_pointing_at_default,
    canonical_path,
    claude_accounts_matching_default_identity,
    codex_accounts_matching_default_identity,
)
from src.models.provider_ledger import AccountUsage

logger = structlog.get_logger()

_FAMILY_PROVIDER = {"claude": "claude", "codex": "codex"}


def accounts_for_default_login(
    accounts: List[ProviderAccount], *, provider: str
) -> List[ProviderAccount]:
    if provider == "claude":
        by_identity = claude_accounts_matching_default_identity(accounts)
        if by_identity:
            return by_identity
    pointed = accounts_pointing_at_default(accounts, provider=provider)
    if provider == "codex" and not pointed:
        return codex_accounts_matching_default_identity(accounts)
    return pointed


def accounts_for_profile_dir(
    accounts: List[ProviderAccount], *, provider: str, profile_dir: str
) -> List[ProviderAccount]:
    wanted = canonical_path(profile_dir)
    if wanted is None:
        return []
    return [
        account
        for account in accounts
        if account.provider == provider
        and canonical_path(profile_dir_for(account)) == wanted
    ]


def resolve_session_account(
    config_path: Path,
    *,
    agent_family: Optional[str],
    profile_dir: Optional[str] = None,
) -> Optional[AccountUsage]:
    provider = _FAMILY_PROVIDER.get(agent_family or "")
    if provider is None:
        return None
    try:
        configured = poller_scan.with_auto_default(
            accounts_store.list_accounts(config_path)
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.debug("session_account_config_unreadable", error=str(exc))
        return None
    matched = (
        accounts_for_profile_dir(configured, provider=provider, profile_dir=profile_dir)
        if profile_dir
        else accounts_for_default_login(configured, provider=provider)
    )
    if len(matched) != 1:
        logger.debug(
            "session_account_undetermined",
            provider=provider,
            candidates=len(matched),
        )
        return None
    wanted = matched[0].id
    try:
        rows = poller.snapshot().accounts
    except Exception as exc:  # noqa: BLE001
        logger.debug("session_account_snapshot_failed", error=str(exc))
        return None
    for row in rows:
        if row.id == wanted:
            return row
    return None
