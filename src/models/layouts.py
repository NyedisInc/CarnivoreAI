
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LayoutMemberModel(BaseModel):
    """One member. Both keys, so a caller can use whichever it already holds.

    ``session_row_id`` is what the terminal page's slot ids carry
    (``terminal:row:<id>``) and what ``/sessions/list`` puts on the WRAPPER
    as ``session_row_id``; ``session_uuid`` is what the drawer, the groups
    and the pins use.
    """

    session_row_id: int
    session_uuid: str
    position: int
    broadcast: bool = Field(
        True, description="Whether the command bar's broadcast reaches this member (issue #837)"
    )


class LayoutModel(BaseModel):
    """One saved Layout."""

    layout_uuid: str = Field(..., description="Stable public identity; the URL is /layout/<uuid>")
    name: str
    position: int = Field(..., description="Drawer order, ascending")
    shape: Dict[str, Any] = Field(
        ..., description="The terminal page arrangement: {layout, groups}, as TerminalLayoutEntry"
    )
    revision: int = Field(..., description="Counts shape changes; send it back as expected_revision")
    source_key: Optional[str] = None
    members: List[LayoutMemberModel] = Field(default_factory=list)
    created_at: str
    updated_at: str
    colour: str = Field(
        ..., description="A key of layout_style.COLOURS, or 'indigo' when nobody has picked one (issue #821)"
    )
    gradient: Optional[str] = Field(default=None, description="A key of layout_style.GRADIENTS, or null")
    animation: str = Field(default="none", description="A key of layout_style.ANIMATIONS")


class LayoutsResponse(BaseModel):
    """Every Layout, plus whether that is known.

    ``status='unavailable'`` with ``layouts=[]`` means the tables could not
    be read, which is not the same claim as an install with no Layouts.
    """

    status: str = Field(..., description="'ok' | 'unavailable'")
    layouts: List[LayoutModel] = Field(default_factory=list)
    detail: Optional[str] = None


class LayoutWriteResponse(BaseModel):
    """What a single-Layout write left behind.

    ``deleted`` is true when the write left fewer than two members and the
    Layout went with it; ``survivor`` then names the one member left (the
    page lands on it as a single agent), or is null when none was left.
    ``created`` is true only when a POST stored a new Layout; a POST whose
    ``source_key`` matched answers the existing one with ``created`` false.
    """

    layout: Optional[LayoutModel] = None
    deleted: bool = False
    survivor: Optional[LayoutMemberModel] = None
    created: bool = False


class CreateLayoutRequest(BaseModel):
    """``POST /layouts``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    shape: Dict[str, Any]
    source_key: Optional[str] = Field(
        default=None, description="Makes the create idempotent (the one-time migration's key)"
    )


class RenameLayoutRequest(BaseModel):
    """``PATCH /layouts/{uuid}``."""

    model_config = ConfigDict(extra="forbid")

    name: str


class ShapeRequest(BaseModel):
    """``PUT /layouts/{uuid}/shape``."""

    model_config = ConfigDict(extra="forbid")

    shape: Dict[str, Any]
    expected_revision: int


class AddMemberRequest(BaseModel):
    """``POST /layouts/{uuid}/members``: exactly one of the two keys."""

    model_config = ConfigDict(extra="forbid")

    session_uuid: Optional[str] = None
    session_row_id: Optional[int] = None
    expected_revision: Optional[int] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "AddMemberRequest":
        if (self.session_uuid is None) == (self.session_row_id is None):
            raise ValueError("send exactly one of session_uuid or session_row_id")
        return self


class LayoutOrderRequest(BaseModel):
    """``PUT /layouts/order``: the WHOLE desired order, never a delta."""

    model_config = ConfigDict(extra="forbid")

    layout_uuids: List[str] = Field(..., max_length=200)


class LayoutStyleRequest(BaseModel):
    """``PUT /layouts/{uuid}/style`` (issue #821).

    The same shape ``session_groups_routes.StyleRequest`` carries for a
    group's colour, gradient and animation - kept as its own class (not
    imported) so a Layout route's OpenAPI schema names itself rather than
    borrowing a group's model name, but validated against the exact same
    shared palette (``src/core/layouts/style.py`` re-exports
    ``session_group_style``'s own ``COLOURS``/``GRADIENTS``/``ANIMATIONS``).
    """

    model_config = ConfigDict(extra="forbid")

    colour: str = Field(..., description="One of layout_style.COLOURS")
    gradient: Optional[str] = Field(
        default=None, description="One of layout_style.GRADIENTS, or null"
    )
    animation: str = Field(default="none", description="One of layout_style.ANIMATIONS")


class LayoutActiveResponse(BaseModel):
    """``PUT /layouts/{uuid}/active``: the lease was renewed."""

    layout_uuid: str
    active: bool = True
    lease_seconds: int = Field(..., description="Renew well inside this; the page renews every 60 s")


class MemberBroadcastRequest(BaseModel):
    """``PUT /layouts/{uuid}/members/{session_uuid}/broadcast``: the member's toggle."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


class BroadcastRequest(BaseModel):
    """``POST /layouts/{uuid}/broadcast``: one command line, sent with one Enter.

    The rules (one line, at most 4096 UTF-8 bytes, no control character
    but tab) live in ``src/core/layouts/broadcast.py``; ``max_length`` here
    only stops an absurd body before it is read.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., max_length=8192)


class BroadcastMemberResult(BaseModel):
    """What happened at one member of a broadcast."""

    session_row_id: int
    session_uuid: str
    status: str = Field(..., description="'sent' | 'skipped_off' | 'skipped_not_live' | 'failed'")
    code: Optional[str] = Field(
        default=None,
        description="Why a failed member failed: pane_dialog_open, paste_not_settled, "
        "paste_unsupported, send_failed",
    )


class BroadcastResponse(BaseModel):
    """``POST /layouts/{uuid}/broadcast``: one result per member, in member order."""

    layout_uuid: str
    results: List[BroadcastMemberResult] = Field(default_factory=list)
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class SkillSuggestion(BaseModel):
    """One completable skill: its name without the sigil, one line, its scope."""

    name: str
    description: str
    scope: str


class SkillSuggestionsResponse(BaseModel):
    """``GET /layouts/{uuid}/skills``: the skills the command bar can complete."""

    sigil: str
    targets: int
    skills: List[SkillSuggestion]
