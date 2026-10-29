
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROVIDER_ACCOUNT_SWITCH_KEY = "provider_account_switch"

DEFAULT_THRESHOLD_PERCENT = 99

MIN_THRESHOLD_PERCENT = 50

SwitchProvider = Literal["claude", "codex"]

_ID_SHAPE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProviderAccountSwitchConfig(BaseModel):
    """Auto-switch on or off, its threshold, and the active account per provider.

    Fields:
        auto_switch: whether the ledger's poll may move the active pointer
            on its own. Default False (owner: "default OFF").
        threshold_percent: the used percent, on the active account's
            short (5h) or weekly window, at which auto-switch moves.
        active_claude: the account id new Claude sessions launch under,
            or None for "not chosen", which injects nothing.
        active_codex: the same, for Codex.
    """

    model_config = ConfigDict(extra="forbid")

    auto_switch: bool = False
    threshold_percent: int = Field(
        DEFAULT_THRESHOLD_PERCENT, ge=MIN_THRESHOLD_PERCENT, le=100
    )
    active_claude: Optional[str] = None
    active_codex: Optional[str] = None

    @field_validator("active_claude", "active_codex")
    @classmethod
    def _pointer_is_an_id(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _ID_SHAPE.fullmatch(value):
            raise ValueError("an active account pointer must be an account id")
        return value

    def active_for(self, provider: str) -> Optional[str]:
        if provider == "claude":
            return self.active_claude
        if provider == "codex":
            return self.active_codex
        return None


def pointer_field(provider: str) -> str:
    if provider not in ("claude", "codex"):
        raise ValueError(f"no account switch exists for provider {provider!r}")
    return f"active_{provider}"
