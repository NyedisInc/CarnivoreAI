
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """Why one step of one member cannot, or did not, go ahead."""

    step: str = Field(..., description="'family' | 'folder' | 'project' | 'skills' | 'session' | 'layout'")
    code: str
    detail: str


class WorktreeView(BaseModel):
    """The worktree a member runs in, planned or made."""

    repo_path: str
    base_branch: str
    branch: str
    path: str
    create: bool = Field(..., description="True when the launch makes it; False when it is reused")
    branch_exists: bool


class FolderView(BaseModel):
    """Where a member runs."""

    mode: str = Field(..., description="'existing' | 'worktree'")
    path: Optional[str] = None
    worktree: Optional[WorktreeView] = None


class ProjectView(BaseModel):
    """The launcher project the folder is (or will be registered as)."""

    known: bool
    name: Optional[str] = None


class SkillView(BaseModel):
    """One catalog skill a member asked for, and what the launch does with it.

    ``state`` in a preview: ``installed`` (already in that folder),
    ``to_install``, ``unknown`` (not in the catalog), ``untrusted``,
    ``catalog_unavailable``. In a launch: ``installed`` (now),
    ``already_present`` or ``refused`` (with ``code``/``detail``, and the
    catalog's own refusal body in ``refusal`` so a ``consent_required``
    carries the sheet). ``consent_sheet`` is the catalog preview body for
    a script-bearing skill, which is what a consent names.
    """

    item_id: str
    state: str
    version: Optional[str] = None
    needs_consent: bool = False
    instructions_write: bool = Field(
        False,
        description="The skill's signed review says it edits CLAUDE.md, "
                    "AGENTS.md or MEMORY.md. A notice, never a gate.",
    )
    instructions_details: List[str] = Field(
        default_factory=list,
        description="The reviewer's own sentences for those findings, "
                    "which name the file. Plain text, capped.",
    )
    instructions_more: int = 0
    consent_sheet: Optional[Dict[str, Any]] = None
    code: Optional[str] = None
    detail: Optional[str] = None
    refusal: Optional[Dict[str, Any]] = None


class MemberPreview(BaseModel):
    """What launching one member would do. ``problems`` empty means it can go."""

    index: int
    label: str
    family: str
    family_name: Optional[str] = None
    folder: FolderView
    project: Optional[ProjectView] = None
    skills: List[SkillView] = Field(default_factory=list)
    skill_roots_to_create: List[str] = Field(
        default_factory=list,
        description="Harness skill roots under this member's folder that do "
                    "not exist yet; the launch creates them itself (contained "
                    "to the folder, symlinks refused) before installing.",
    )
    opening_prompt: bool = False
    problems: List[Problem] = Field(default_factory=list)


class LaunchPreviewResponse(BaseModel):
    """``POST /blueprints/{uuid}/launch/preview``. Writes nothing."""

    blueprint_uuid: str
    name: str
    worktree_root: str
    members: List[MemberPreview]


class LaunchedSession(BaseModel):
    """The session a member became."""

    id: str
    tmux_session: Optional[str] = None
    session_row_id: Optional[int] = None
    session_uuid: Optional[str] = None


class MemberOutcome(BaseModel):
    """What launching one member did.

    ``state`` is ``launched`` (created now), ``reused`` (the member was already a
    running session, so nothing was created and its theme is untouched),
    ``woken`` (the member was an asleep session, resumed through the wake
    route and otherwise untouched) or ``failed``; a failed member names the
    ``step`` it stopped at in ``problem``. Nothing a member did before it
    failed is undone (a worktree made, a project registered, a skill
    installed stay), and no launched session is ever rolled back.
    """

    index: int
    label: str
    state: str = Field(..., description="'launched' | 'reused' | 'woken' | 'failed'")
    folder: FolderView
    project: Optional[ProjectView] = None
    skills: List[SkillView] = Field(default_factory=list)
    session: Optional[LaunchedSession] = None
    problem: Optional[Problem] = None


class LaunchResponse(BaseModel):
    """``POST /blueprints/{uuid}/launch``.

    ``complete`` is true only when every requested member launched.
    ``layout`` is the Layout the launched, reused and woken members were saved
    as (two or more), else null with ``layout_detail`` saying why;
    ``layout_updated`` is true when it was the blueprint's existing Layout,
    updated in place (``overwrite_layout``), false when it is a new one.
    """

    blueprint_uuid: str
    name: str
    complete: bool
    members: List[MemberOutcome]
    layout: Optional[Dict[str, Any]] = None
    layout_detail: Optional[str] = None
    layout_updated: bool = False
