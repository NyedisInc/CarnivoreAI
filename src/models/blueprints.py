
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.agent_wrappers import WRAPPER_ID_PATTERN
from src.models.catalog_api import InstallConsent
from src.models.model_ids import describe_model_id_rejection, is_valid_model_id
from src.models.terminal_dims import TermCols, TermRows

SPEC_VERSION = 1

NAME_MAX = 60

SESSIONS_MAX = 16

SKILLS_PER_SESSION_MAX = 16

LABEL_MAX = 120

PATH_MAX = 4096

BRANCH_MAX = 200

OPENING_PROMPT_MAX_BYTES = 8192

PROMPT_FAMILIES = ("claude", "codex")

CATALOG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}/[a-z0-9][a-z0-9._-]{0,63}$")

FAMILY_RE = re.compile(WRAPPER_ID_PATTERN)

HOST_KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
BRANCH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/+@-]*$")

MEMBER_SLOT_RE = re.compile(r"^terminal:member:(\d{1,2})$")

_BARE_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _no_controls(value: str, what: str) -> str:
    if any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ValueError(f"{what} holds a control character")
    return value


def check_opening_prompt(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    if "\x00" in value:
        raise ValueError("an opening prompt cannot contain a NUL character")
    if len(value.encode("utf-8")) > OPENING_PROMPT_MAX_BYTES:
        raise ValueError(f"an opening prompt is at most {OPENING_PROMPT_MAX_BYTES} bytes")
    if value.startswith("-"):
        raise ValueError("an opening prompt cannot start with '-', the CLI would read it as an option")
    if _BARE_WORD_RE.match(value.strip()):
        raise ValueError(
            "a one-word opening prompt could be read as a subcommand; write a sentence")
    return value


class ExistingFolder(BaseModel):
    """Run the session in a folder that already exists."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["existing"]
    path: str = Field(..., min_length=1, max_length=PATH_MAX)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _no_controls(value.strip(), "a folder path")


class WorktreeFolder(BaseModel):
    """Run the session in a NEW git worktree created at launch.

    ``repo_path`` is the repository's top level; the worktree lands at
    ``<worktree root>/<repo name>/<branch slug>`` on ``branch``, made from
    ``base_branch`` (or checked out when ``branch`` already exists).
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["worktree"]
    repo_path: str = Field(..., min_length=1, max_length=PATH_MAX)
    base_branch: str = Field(..., min_length=1, max_length=BRANCH_MAX)
    branch: str = Field(..., min_length=1, max_length=BRANCH_MAX)

    @field_validator("repo_path")
    @classmethod
    def _repo(cls, value: str) -> str:
        return _no_controls(value.strip(), "a repository path")

    @field_validator("base_branch", "branch")
    @classmethod
    def _branch(cls, value: str) -> str:
        if not BRANCH_RE.match(value):
            raise ValueError(
                "a branch name uses letters, digits and . _ / + @ - and does not start with '-'")
        return value


Folder = Union[ExistingFolder, WorktreeFolder]


class MemberBackground(BaseModel):
    """A session's terminal background override (the body of ``PATCH /sessions/{name}/background``)."""

    model_config = ConfigDict(extra="forbid")

    theme_id: Optional[str] = Field(None, max_length=64)
    dim: Optional[float] = Field(None, ge=0, le=1)
    disabled: bool = False

    @field_validator("theme_id")
    @classmethod
    def _theme_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return _no_controls(value.strip(), "a background theme id")


class BlueprintSession(BaseModel):
    """One member of the team."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1, max_length=LABEL_MAX)
    family: str = Field(..., description="'claude' | 'codex' | 'shell' | a configured wrapper id")
    model: Optional[str] = None
    folder: Folder = Field(..., discriminator="mode")
    skills: List[str] = Field(default_factory=list, max_length=SKILLS_PER_SESSION_MAX)
    opening_prompt: Optional[str] = None
    session_uuid: Optional[str] = Field(
        None, max_length=64,
        description="The session this member was saved from (``sessions.session_uuid``); a launch reuses it while it is live")
    theme: Optional[str] = Field(
        None, max_length=64,
        description="The theme this member's session is pinned to on create; absent keeps the folder's default")
    keep_awake: Optional[bool] = Field(
        None, description="Keep this session awake (the coffee cup); applied on create, absent leaves it off")
    notifications_muted: Optional[bool] = Field(
        None, description="Mute this session's notifications; applied on create, absent leaves it unmuted")
    background: Optional[MemberBackground] = Field(
        None, description="This session's terminal background override; applied on create, absent keeps the theme's own")
    host_key: Optional[str] = Field(
        None, description="A paired computer (its ``hosts.key``) to create this member on; absent or 'local' is this computer")

    @field_validator("host_key")
    @classmethod
    def _host_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip() or value.strip() == "local":
            return None
        if not HOST_KEY_RE.fullmatch(value.strip()):
            raise ValueError("a member host is a paired computer's key")
        return value.strip()

    @field_validator("session_uuid", "theme")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return _no_controls(value.strip(), "a session id or theme")

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("a session label cannot be empty")
        return _no_controls(cleaned, "a session label")

    @field_validator("family")
    @classmethod
    def _family(cls, value: str) -> str:
        if not FAMILY_RE.match(value):
            raise ValueError("family is 'claude', 'codex', 'shell' or a wrapper id")
        return value

    @field_validator("model")
    @classmethod
    def _model(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        if not is_valid_model_id(value):
            raise ValueError(describe_model_id_rejection(value))
        return value

    @field_validator("skills")
    @classmethod
    def _skills(cls, value: List[str]) -> List[str]:
        for item in value:
            if not CATALOG_ID_RE.match(item):
                raise ValueError(f"{item!r} is not a catalog id ('<publisher>/<name>')")
        if len(set(value)) != len(value):
            raise ValueError("a skill is listed twice")
        return value

    @field_validator("opening_prompt")
    @classmethod
    def _prompt(cls, value: Optional[str]) -> Optional[str]:
        return check_opening_prompt(value)

    @model_validator(mode="after")
    def _prompt_family(self) -> "BlueprintSession":
        if self.opening_prompt is not None and self.family == "shell":
            raise ValueError("an opening prompt is for claude and codex sessions, not a shell")
        return self


class BlueprintSpec(BaseModel):
    """The blueprint document, v1: what the table stores and ``swarm.json`` holds.

    ``shape_template`` is optional: a terminal arrangement
    (``TerminalLayoutEntry``) whose terminal slots are
    ``terminal:member:<index into sessions>``. A launch that brings every
    member up saves the Layout in that arrangement; otherwise, or with no
    template, the Layout shows the launched members side by side.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = SPEC_VERSION
    name: str = Field(..., min_length=1, max_length=NAME_MAX)
    shape_template: Optional[Dict[str, Any]] = None
    sessions: List[BlueprintSession] = Field(..., min_length=1, max_length=SESSIONS_MAX)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("a blueprint name cannot be empty")
        return _no_controls(cleaned, "a blueprint name")

    @model_validator(mode="after")
    def _members(self) -> "BlueprintSpec":
        folded = [s.label.casefold() for s in self.sessions]
        if len(set(folded)) != len(folded):
            raise ValueError("two sessions share a label; every member needs its own")
        if self.shape_template is not None:
            from src.core.blueprints_shape import check_template

            self.shape_template = check_template(self.shape_template, len(self.sessions))
        return self


class BlueprintModel(BaseModel):
    """One stored blueprint."""

    blueprint_uuid: str
    name: str
    spec: BlueprintSpec
    created_at: str
    updated_at: str


class BlueprintsResponse(BaseModel):
    """Every blueprint, plus whether that is known (``unavailable`` = unreadable)."""

    status: str = Field(..., description="'ok' | 'unavailable'")
    blueprints: List[BlueprintModel] = Field(default_factory=list)
    detail: Optional[str] = None


class BlueprintWriteRequest(BaseModel):
    """``POST /blueprints`` and ``PUT /blueprints/{uuid}``."""

    model_config = ConfigDict(extra="forbid")

    spec: BlueprintSpec


class FromLayoutRequest(BaseModel):
    """``POST /blueprints/from-layout/{layout_uuid}``: an optional name."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=NAME_MAX)


class ProjectFileRequest(BaseModel):
    """``POST /blueprints/{uuid}/export`` and ``POST /blueprints/import``.

    ``project_path`` names a known, non-archived project; the file is
    always ``<project>/.carnivore/swarm.json``. ``name`` on an import
    stores it under another name (the file's own name is taken).
    """

    model_config = ConfigDict(extra="forbid")

    project_path: str = Field(..., min_length=1, max_length=PATH_MAX)
    name: Optional[str] = Field(None, max_length=NAME_MAX)


class ExportResponse(BaseModel):
    """Where the spec was written."""

    path: str
    blueprint_uuid: str


class WorktreeSettings(BaseModel):
    """``GET``/``PUT /blueprints/settings``: where new worktrees are made."""

    model_config = ConfigDict(extra="forbid")

    worktree_root: str = Field(..., min_length=1, max_length=PATH_MAX)


class LaunchRequest(BaseModel):
    """``POST /blueprints/{uuid}/launch`` (and ``/launch/preview``).

    ``consents`` is keyed by catalog id and is the SAME three-field
    consent ``POST /catalog/install`` takes: a script-bearing skill with
    no entry, or an entry naming other bytes, is refused. ``members``
    launches a subset (indices into ``sessions``), for a retry after a
    partial launch; absent means all. ``cols``/``rows`` birth each pane at
    the client's size.
    """

    model_config = ConfigDict(extra="forbid")

    consents: Optional[Dict[str, InstallConsent]] = None
    members: Optional[List[int]] = Field(None, max_length=SESSIONS_MAX)
    cols: Optional[TermCols] = None
    rows: Optional[TermRows] = None
    overwrite_layout: bool = Field(
        False,
        description="Update the Layout this blueprint already saved, in place. Without "
                    "it a launch that would save over an existing Layout is refused "
                    "(409 'layout_exists') before anything is launched.",
    )

    @field_validator("members")
    @classmethod
    def _members(cls, value: Optional[List[int]]) -> Optional[List[int]]:
        if value is None:
            return None
        if any(i < 0 or i >= SESSIONS_MAX for i in value) or len(set(value)) != len(value):
            raise ValueError("members are distinct indices into sessions")
        return sorted(value)
