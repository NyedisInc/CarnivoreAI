
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class ActiveAccountState(BaseModel):
    """One provider's active account, and which rung decided it.

    Fields:
        provider: 'claude' or 'codex'.
        account_id: the account new sessions launch under, or None.
        source: 'pointer' (chosen here), 'default_login' (nothing chosen,
            so the provider's own default login, matched to an account),
            or 'none' (nothing chosen and the default login is not one
            this install tracks).
        pointer: the stored pointer, even a stale one.
        next_order: ids of the other accounts of this provider the
            auto-switch rule would move to, best first
            (``decide.rank_candidates``); accounts it would never pick
            are absent.
    """

    provider: Literal["claude", "codex"]
    account_id: Optional[str] = None
    source: Literal["pointer", "default_login", "none"]
    pointer: Optional[str] = None
    next_order: List[str] = []


class LastSwitch(BaseModel):
    """The most recent switch this server process made.

    Fields: provider; from_account_id (None when nothing was active);
      to_account_id; reason ('manual', 'auto' or 'limit_rotated'); window_kind and
      used_pct (the trigger, for an automatic switch); at (ISO 8601).
    """

    provider: str
    from_account_id: Optional[str] = None
    to_account_id: str
    reason: Literal["manual", "auto", "auto_restart", "limit_rotated"]
    window_kind: Optional[str] = None
    used_pct: Optional[float] = None
    window_seconds: Optional[int] = None
    at: str


class AccountSwitchState(BaseModel):
    """`GET /provider-ledger/switch`: everything the three surfaces draw.
    """

    auto_switch: bool
    threshold_percent: int
    active: List[ActiveAccountState]
    last_switch: Optional[LastSwitch] = None
    restarts_running_sessions: bool = False


class AccountSwitchWrite(BaseModel):
    """`PUT /provider-ledger/switch`: the toggle, and optionally its threshold."""

    model_config = ConfigDict(extra="forbid")

    auto_switch: bool
    threshold_percent: Optional[int] = None


class RunningElsewhere(BaseModel):
    """A running session still on an account other than its provider's active one.

    Fields: session_id (the app's id; not a tmux name); tmux_session;
      label (None when the session has none); status (its light); provider;
      account_id (the account the pane runs on); active_account_id.
    """

    session_id: str
    tmux_session: str
    label: Optional[str] = None
    status: Optional[str] = None
    provider: str
    account_id: str
    active_account_id: str


class AccountActivated(BaseModel):
    """`POST /provider-ledger/accounts/{id}/activate`: the new state, and who is left behind."""

    state: AccountSwitchState
    running_elsewhere: List[RunningElsewhere]
