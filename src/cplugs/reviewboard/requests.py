
from __future__ import annotations

from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from src.cplugs.sdk import browser_pages
from src.cplugs.reviewboard.layers.models import CanvasLayer, RequestLayer
from src.cplugs.reviewboard.schema import (MAX_ANCHORS, MAX_MAX_WIDTH, MIN_MAX_WIDTH, MAX_PROMPTS, MAX_ROUND_NOTES, MAX_TEXT, MAX_VIEWS, Anchor, AnchorNote, Answer, Commit, Label,
                                           Payload, Prompt, RevisionId, RoundContext, RoundId, Uuid, ViewId)

SlugName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")]
Page = Annotated[str, StringConstraints(min_length=1)]


class _Body(BaseModel):
    """Base of every request body: an unknown field is an error."""

    model_config = ConfigDict(extra="forbid")


def checked_look_name(value: Optional[str], icon: bool) -> Optional[str]:
    try:
        browser_pages.check_look(None if icon else value, value if icon else None)
    except browser_pages.RowLookRefused as exc:
        raise ValueError(str(exc)) from exc
    return value


class LookChecked(BaseModel):
    """Mixin for a body that carries the optional row look: the ``color`` and ``icon`` fields stay on the body, in its own order, and these
    validators check them. ``check_fields=False`` because this class declares neither field."""

    @field_validator("color", check_fields=False)
    @classmethod
    def _color(cls, value: Optional[str]) -> Optional[str]:
        return checked_look_name(value, False)

    @field_validator("icon", check_fields=False)
    @classmethod
    def _icon(cls, value: Optional[str]) -> Optional[str]:
        return checked_look_name(value, True)


class ExtraView(_Body):

    id: ViewId
    label: Label
    html: Page


class RevisionBody(_Body):

    summary: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    html: Optional[Page] = None
    viewport: Optional[int] = Field(default=None, ge=240, le=2560)
    views: List[ExtraView] = Field(default_factory=list, max_length=MAX_VIEWS - 1)
    prompts: List[Prompt] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchors: List[Anchor] = Field(default_factory=list, max_length=MAX_ANCHORS)
    answers_round: Optional[RoundId] = None
    source_commit: Optional[Commit] = None
    request_review: bool = True
    inline_picks: Optional[bool] = None
    payload_mode: Optional[bool] = None
    layer: Optional[RequestLayer] = None
    max_width: Optional[int] = Field(default=None, ge=MIN_MAX_WIDTH, le=MAX_MAX_WIDTH)

    @model_validator(mode="after")
    def _layer_rules(self) -> "RevisionBody":
        if self.layer is None:
            if self.html is None:
                raise ValueError("html is required (the page), or name a questions or rows layer")
            return self
        if self.payload_mode is False:
            raise ValueError("layer is payload mode: payload_mode false cannot be combined with a layer")
        if self.prompts:
            raise ValueError("a layer revision carries no prompts (one layer at a time)")
        if isinstance(self.layer, CanvasLayer) and self.html is None:
            raise ValueError("a canvas layer needs html (the page)")
        return self


class TaskRef(_Body):

    item_id: int = Field(ge=1)


class CreateBody(LookChecked, RevisionBody):

    slug_name: SlugName
    title: Label
    kind: str = Field(default="mockup", pattern=r"^(mockup|flowchart|copy|other)$")
    task: TaskRef
    viewport: int = Field(ge=240, le=2560)
    color: Optional[str] = None
    icon: Optional[str] = None


class ReviseBody(RevisionBody):

    base_etag: Optional[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]] = None


class TicketBody(_Body):

    view: ViewId = "main"


class OpenBody(LookChecked, _Body):

    revision: Optional[RevisionId] = None
    color: Optional[str] = None
    icon: Optional[str] = None


Etag = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DraftBody(_Body):

    rev: int = Field(ge=0)
    revision: RevisionId
    answers: List[Answer] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchor_notes: List[AnchorNote] = Field(default_factory=list, max_length=MAX_ANCHORS)
    note: Annotated[str, StringConstraints(max_length=MAX_ROUND_NOTES)] = ""
    client_round_id: Uuid


class RoundBody(_Body):

    base_etag: Optional[Etag] = None
    client_round_id: Uuid
    revision: RevisionId
    answers: List[Answer] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchor_notes: List[AnchorNote] = Field(default_factory=list, max_length=MAX_ANCHORS)
    note: Annotated[str, StringConstraints(max_length=MAX_ROUND_NOTES)] = ""
    context: RoundContext = Field(default_factory=RoundContext)
    payload: Optional[Payload] = None


class SaveBody(_Body):

    base_etag: Optional[Etag] = None
    revision: RevisionId
    payload: Payload
    note: Optional[Annotated[str, StringConstraints(max_length=MAX_TEXT)]] = None


class PayloadDraftBody(_Body):

    revision: RevisionId
    payload: Payload


class RelinkBody(_Body):

    base_etag: Optional[Etag] = None
    item_id: int = Field(ge=1)


class ResendBody(_Body):
    pass
