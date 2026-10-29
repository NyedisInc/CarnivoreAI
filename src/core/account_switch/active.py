
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import ProviderAccount
from src.core.provider_ledger.poller_scan import AUTO_DEFAULT_ACCOUNT_ID
from src.core.session_token_usage.account_resolve import accounts_for_default_login

PROVIDERS = ("claude",)

POINTER = "pointer"
DEFAULT_LOGIN = "default_login"
NONE = "none"


@dataclass(frozen=True)
class ActiveAccount:

    provider: str
    account_id: Optional[str]
    source: str
    pointer: Optional[str]


def find_account(
    accounts: List[ProviderAccount], account_id: Optional[str], provider: str
) -> Optional[ProviderAccount]:
    if account_id is None:
        return None
    return next(
        (a for a in accounts if a.id == account_id and a.provider == provider),
        None,
    )


def pointer_for(account: ProviderAccount) -> Optional[str]:
    return None if account.id == AUTO_DEFAULT_ACCOUNT_ID else account.id


def effective_active(
    accounts: List[ProviderAccount],
    switch: ProviderAccountSwitchConfig,
    provider: str,
) -> ActiveAccount:
    pointer = switch.active_for(provider)
    if find_account(accounts, pointer, provider) is not None:
        return ActiveAccount(provider, pointer, POINTER, pointer)
    matched = accounts_for_default_login(accounts, provider=provider)
    if len(matched) == 1:
        return ActiveAccount(provider, matched[0].id, DEFAULT_LOGIN, pointer)
    return ActiveAccount(provider, None, NONE, pointer)
