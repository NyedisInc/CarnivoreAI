
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import structlog

from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR, ProviderAccount
from src.core.provider_ledger import credential_signal
from src.core.provider_ledger.default_login import default_login_is_configured
from src.core.provider_ledger.poller_state import AccountState

logger = structlog.get_logger()

__all__ = [
    "AUTO_DEFAULT_ACCOUNT_ID",
    "SIGNAL_WATCHED_STATES",
    "default_login_row",
    "mark_changed_signals",
    "read_accounts",
    "reconcile",
    "with_auto_default",
]

AUTO_DEFAULT_ACCOUNT_ID = "auto-claude-default"

DEFAULT_LOGIN_NAME = "this device's claude login"

DEFAULT_LOGIN_SHORT_NAME = "this device"

SIGNAL_WATCHED_STATES = frozenset({"missing", "expired", "refused", "unknown"})


async def read_accounts(
    list_accounts: Callable[[Path], List[ProviderAccount]],
    config_path: Path,
) -> Optional[List[ProviderAccount]]:
    try:
        return await asyncio.to_thread(list_accounts, config_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning(
            "provider_ledger_accounts_unreadable",
            error=f"{type(exc).__name__}: {exc}",
        )
        return None


def with_auto_default(
    accounts: List[ProviderAccount], label: Optional[str] = None
) -> List[ProviderAccount]:
    if default_login_is_configured(accounts):
        return accounts
    return [*accounts, default_login_row(label)]


def default_login_row(label: Optional[str] = None) -> ProviderAccount:
    return ProviderAccount(
        id=AUTO_DEFAULT_ACCOUNT_ID,
        name=label or DEFAULT_LOGIN_NAME,
        short_name=None if label else DEFAULT_LOGIN_SHORT_NAME,
        provider="claude",
        claude_config_dir=DEFAULT_CLAUDE_CONFIG_DIR,
        managed=False,
    )


def reconcile(
    states: Dict[str, AccountState],
    poll_soon: Set[str],
    accounts: List[ProviderAccount],
    now: datetime,
) -> None:
    seen = set()
    for account in accounts:
        seen.add(account.id)
        state = states.get(account.id)
        if state is None:
            states[account.id] = AccountState(account=account, next_poll_at=now)
            continue
        if state.account != account:
            renamed_only = state.account.model_copy(
                update={"name": account.name, "short_name": account.short_name}) == account
            state.account = account
            if not renamed_only:
                state.next_poll_at = now
        if account.id in poll_soon:
            state.next_poll_at = now
    for gone in [key for key in states if key not in seen]:
        del states[gone]
    poll_soon.clear()


async def mark_changed_signals(
    states: Dict[str, AccountState], now: datetime
) -> None:
    watched = [
        state
        for state in states.values()
        if state.credential_state in SIGNAL_WATCHED_STATES
    ]
    if not watched:
        return

    def gather() -> Dict[str, tuple]:
        return {
            state.account.id: credential_signal.signal_stamp(
                credential_signal.signal_paths(state.account)
            )
            for state in watched
        }

    stamps = await asyncio.to_thread(gather)
    for state in watched:
        stamp = stamps[state.account.id]
        if stamp != state.last_signal:
            state.last_signal = stamp
            state.next_poll_at = now
