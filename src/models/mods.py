
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ModEntry(BaseModel):
    """One installed or registered mod. ``state`` is on (every settings group), off (none) or partial."""

    model_config = ConfigDict(extra="forbid")

    mod_id: str
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    path: str
    source: str
    install_id: Optional[str] = None
    item_id: Optional[str] = None
    state: str
    registered_in: int
    groups_total: int
    is_mod: bool
    present: bool
    removable: bool


class ModGroup(BaseModel):
    """One real settings file; ``status`` is ok, settings_missing or settings_unparseable."""

    model_config = ConfigDict(extra="forbid")

    label: str
    members: List[str]
    real_path_display: str
    status: str


class ModClaude(BaseModel):
    """The installed claude CLI: its version text (null when unknown) and whether it loads mods by default."""

    model_config = ConfigDict(extra="forbid")

    version: Optional[str] = None
    ok: bool


class ModAccounts(BaseModel):
    """Whether the Claude account list could be read: ``ok`` or ``accounts_unreadable`` (writes are refused)."""

    model_config = ConfigDict(extra="forbid")

    status: str


class ModsResponse(BaseModel):
    """``GET /mods``."""

    model_config = ConfigDict(extra="forbid")

    mods: List[ModEntry]
    groups: List[ModGroup]
    claude: ModClaude
    accounts: ModAccounts


class SetEnabledRequest(BaseModel):
    """Body of ``PUT /mods/{mod_id}/enabled``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


class GroupResult(BaseModel):
    """What one settings group answered to a write: ok, settings_missing, settings_unparseable, settings_changed."""

    model_config = ConfigDict(extra="forbid")

    real: str
    members: List[str]
    status: str


class SetEnabledResponse(BaseModel):
    """``PUT /mods/{mod_id}/enabled``: the mod as it now stands plus each group's result."""

    model_config = ConfigDict(extra="forbid")

    mod: ModEntry
    results: List[GroupResult]


class RemoveResponse(BaseModel):
    """``DELETE /mods/{mod_id}``: where the folder went."""

    model_config = ConfigDict(extra="forbid")

    mod_id: str
    name: Optional[str] = None
    trashed_to: str
    results: List[GroupResult]


class ModHookEvents(BaseModel):
    """The hook events one module of a mod handles, as ``claude plugin validate`` listed them."""

    model_config = ConfigDict(extra="forbid")

    module: str
    events: List[str]


class ModApiCalls(BaseModel):
    """The Claude Code API calls one module of a mod makes, as ``claude plugin validate`` listed them."""

    model_config = ConfigDict(extra="forbid")

    module: str
    calls: List[str]


class ModGatingHook(BaseModel):
    """One hook that can gate a tool call or prompt; ``has_catch`` false means a crash there blocks the turn."""

    model_config = ConfigDict(extra="forbid")

    module: str
    pattern: str
    hook: str
    has_catch: bool


class ModReport(BaseModel):
    """What a staged mod hooks and calls, parsed from ``claude plugin validate --json --strict`` (docs/mods.md).

    The parse never fails: a note the two patterns do not match goes to ``notes_raw``. The checker is not a
    sandbox; the consent sheet says so.
    """

    model_config = ConfigDict(extra="forbid")

    claude_version: str
    hooks: List[ModHookEvents] = []
    calls: List[ModApiCalls] = []
    gating: List[ModGatingHook] = []
    warnings: List[str] = []
    spends_plan_usage: bool = False
    notes_raw: List[str] = []
