
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
    """One provider's active account and how it was decided.

    Fields:
        provider: 'claude' or 'codex'.
        account_id: the account new sessions launch under, or None.
        source: 'pointer', 'default_login' or 'none'.
        pointer: the stored pointer, even when it was not honoured, so a
            screen can tell a stale pointer from no pointer.
    """

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
    """The value to store in ``active_<provider>`` to make this account active.

    Description: THE BUILT-IN DEFAULT LOGIN IS "NO POINTER". Its row is
      synthesized (`poller_scan.with_auto_default`), never in config.json,
      and new panes on it are launched with ``CLAUDE_CONFIG_DIR`` REMOVED,
      which is exactly what an absent pointer means. Storing its synthetic
      id would leave a pointer at an account the file does not hold.
    Inputs: account (ProviderAccount) - the row being activated.
    Output: str | None - the account id, or None for the built-in login.
    Example: pointer_for(default_login_row())  # None
    """
    return None if account.id == AUTO_DEFAULT_ACCOUNT_ID else account.id


def effective_active(
    accounts: List[ProviderAccount],
    switch: ProviderAccountSwitchConfig,
    provider: str,
) -> ActiveAccount:
    """Resolve one provider's active account. See the module docstring.

    Inputs: accounts (list[ProviderAccount]) - the configured rows;
      switch (ProviderAccountSwitchConfig); provider (str).
    Output: ActiveAccount.
    Example: effective_active(rows, switch, 'claude').account_id
    """
    pointer = switch.active_for(provider)
    if find_account(accounts, pointer, provider) is not None:
        return ActiveAccount(provider, pointer, POINTER, pointer)
    matched = accounts_for_default_login(accounts, provider=provider)
    if len(matched) == 1:
        return ActiveAccount(provider, matched[0].id, DEFAULT_LOGIN, pointer)
    return ActiveAccount(provider, None, NONE, pointer)
