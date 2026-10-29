"""What one polled account holds, and the three things a loop needs first.

``AccountState`` IS IN MEMORY ONLY AND IS NEVER PERSISTED. A reading is
worth exactly as long as the process that took it: a usage percentage
restored from disk at boot would be presented as current while being
arbitrarily old, and the row carries no field that could say so. A fresh
process starts every account at ``unknown``, which is a real answer and
is never ``idle``-shaped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx

from src.config import settings
from src.config.provider_accounts import ProviderAccount
from src.models.provider_ledger import AccountUsage, PokeStatus, UsageWindow

REQUEST_TIMEOUT_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 5.0


def utc_now() -> datetime:
    """The current moment, aware, in UTC.

    Inputs: none.
    Output: datetime - timezone aware.
    Example: utc_now()
    """
    return datetime.now(timezone.utc)


def default_config_path() -> Path:
    return Path(settings.auth_config_file).expanduser()


def build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
        follow_redirects=False,
        trust_env=False,
    )


@dataclass
class AccountState:

    account: ProviderAccount
    next_poll_at: Optional[datetime] = None
    credential_state: str = "unknown"
    windows: List[UsageWindow] = field(default_factory=list)
    plan: Optional[str] = None
    identity: Optional[str] = None
    fetched_at: Optional[datetime] = None
    error: Optional[str] = None
    rate_limited_interval: Optional[float] = None
    last_signal: Optional[tuple] = None
    login_expires_at: Optional[datetime] = None
    poke_state: str = "idle"
    poke_last_at: Optional[datetime] = None
    poke_error: Optional[str] = None
    poke_for_expiry: Optional[datetime] = None
    refresh_check_at: Optional[datetime] = None
    setup_complete: Optional[bool] = None


def poke_status(state: "AccountState") -> Optional[PokeStatus]:
    """What to publish about this account's refresh poke, or nothing.

    Description: ``None`` MEANS NOTHING HAS EVER HAPPENED, which is the
      state of every healthy account and of every codex row, and it is a
      different fact from a poke that was attempted and did nothing. A
      screen that was handed ``{state: "idle"}`` for an account nobody
      has ever poked could not tell the two apart.
    Inputs: state (AccountState).
    Output: PokeStatus | None.
    Example: poke_status(state).error  # 'poke_no_refresh'
    """
    if state.poke_last_at is None and state.poke_error is None:
        return None
    return PokeStatus(
        state=state.poke_state,
        last_at=state.poke_last_at,
        error=state.poke_error,
    )


def account_row(state: "AccountState") -> AccountUsage:
    return AccountUsage(
        id=state.account.id,
        name=state.account.name,
        provider=state.account.provider,
        plan=state.plan,
        identity=state.identity,
        credential_state=state.credential_state,
        fetched_at=state.fetched_at,
        next_poll_at=state.next_poll_at,
        error=state.error,
        windows=list(state.windows),
        color=state.account.color,
        managed=state.account.managed,
        login_expires_at=state.login_expires_at,
        poke=poke_status(state),
        short_name=state.account.short_name,
        setup_complete=state.setup_complete,
    )


_PASS_CLOCK_FIELDS = frozenset({"next_poll_at"})


def rows_fingerprint(rows: List[AccountUsage], *, alive: bool) -> str:
    shown = [row.model_dump(mode="json", exclude=set(_PASS_CLOCK_FIELDS)) for row in rows]
    return json.dumps({"rows": shown, "alive": alive}, sort_keys=True)
