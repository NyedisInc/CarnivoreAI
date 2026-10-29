
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

CLAUDE = "claude"
CODEX = "codex"

SCOPE_PERSONAL = "personal"
SCOPE_PROJECT = "project"
SCOPE_PLUGIN = "plugin"
SCOPE_SYSTEM = "system"

CLAUDE_STATES: Tuple[str, ...] = ("on", "name-only", "user-invocable-only", "off")
CODEX_STATES: Tuple[str, ...] = ("on", "off")

PLUGIN_NO_TOGGLE_REASON = "plugin skills switch with the whole plugin"


@dataclass(frozen=True)
class SkillRoot:

    root_key: str
    harness: str
    scope: str
    path: str
    read_only: bool = False
    is_symlink: bool = False
    group_id: Optional[str] = None
    project_path: Optional[str] = None
    plugin: Optional[str] = None
    exists: bool = True


@dataclass(frozen=True)
class ProfileGroup:

    group_id: str
    profiles: Tuple[str, ...]
    skills_path: str
    settings_path: str
    own_folder: bool
    exists: bool


@dataclass(frozen=True)
class Profile:

    profile_id: str
    directory: str


@dataclass(frozen=True)
class SkillLocation:

    location_id: str
    root_key: str
    folder: str
    name: str
    harness: str
    scope: str
    path: str
    description: str
    description_tokens_est: int
    is_symlink: bool
    link_target: Optional[str]
    read_only: bool
    plugin: Optional[str]
    project_path: Optional[str]
    toggle: Dict[str, object] = field(default_factory=dict)
    state: str = "on"
    state_source: Optional[str] = None
    managed: Optional[Dict[str, object]] = None
    shadowed_by: Optional[str] = None
    shadows: Tuple[str, ...] = ()
    tokens_label: str = "est."
    extends: Optional[str] = None
    guide_rev: Optional[int] = None
    behind_rules: Optional[Dict[str, object]] = None


@dataclass(frozen=True)
class SkillGroup:

    name: str
    locations: Tuple[SkillLocation, ...]


class OverrideError(Exception):
    """A skill toggle that was refused or could not be written.

    Fields: status (HTTP status), code (stable machine token such as
    ``settings_unparseable``, ``settings_changed``, ``plugin_managed``,
    ``codex_config_edit_unsafe``), detail (one plain sentence; never a file
    value).
    """

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
