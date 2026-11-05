
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.federation.peer_ledger import identity_key
from src.models.provider_ledger import AccountUsage, PokeStatus, UsageWindow

STATUS_PATH = "/federation/pack/ledger-status"
SESSIONS_PATH = "/federation/pack/ledger-sessions"
CAP_LEDGER_STATUS = "pack.ledger.status"


class WireSession(BaseModel):
    """One open session on an account. ``tmux`` is set only for a session on the SENDER itself (the receiver derives a
    ``remote:peer-...`` id from it); ``computer_id`` lets a receiver drop its own sessions when an owner echoes them back."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    tmux: Optional[str] = Field(default=None, max_length=200)
    computer: Optional[str] = Field(default=None, max_length=64)
    computer_id: Optional[str] = Field(default=None, max_length=64)


class LedgerStatusBody(BaseModel):
    """The owner's status of one relayed account, as pushed to each computer holding a copy of it."""

    model_config = ConfigDict(extra="forbid")

    account_key: str = Field(max_length=64)
    provider: str = Field(pattern="^(claude|codex)$")
    name: Optional[str] = Field(default=None, max_length=200)
    identity: Optional[str] = Field(default=None, max_length=320)
    identity_key: Optional[str] = Field(default=None, max_length=64)
    plan: Optional[str] = Field(default=None, max_length=100)
    credential_state: str = Field(max_length=32)
    fetched_at: Optional[datetime] = None
    error: Optional[str] = Field(default=None, max_length=500)
    windows: List[UsageWindow] = Field(default_factory=list, max_length=20)
    poke: Optional[PokeStatus] = None
    login_expires_at: Optional[datetime] = None
    sessions: List[WireSession] = Field(default_factory=list, max_length=100)


class LedgerSessionsBody(BaseModel):
    """A computer's own sessions running on its relayed copy of ``account_key``, pushed back to the owner."""

    model_config = ConfigDict(extra="forbid")

    account_key: str = Field(max_length=64)
    provider: str = Field(pattern="^(claude|codex)$")
    sessions: List[WireSession] = Field(default_factory=list, max_length=100)


def status_of(row: AccountUsage, sessions: List[WireSession]) -> LedgerStatusBody:
    return LedgerStatusBody(
        account_key=row.id, provider=row.provider, name=row.name[:200] or None, identity=(row.identity or None) and row.identity[:320],
        identity_key=identity_key(row.provider, row.identity), plan=row.plan,
        credential_state=row.credential_state, fetched_at=row.fetched_at, error=(row.error or None) and row.error[:500],
        windows=list(row.windows), poke=row.poke, login_expires_at=row.login_expires_at, sessions=sessions)
