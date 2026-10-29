
from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import Field, StringConstraints

from src.cplugs.reviewboard.requests import Etag, ExtraView, Page, SlugName, TaskRef, _Body, LookChecked
from src.cplugs.reviewboard.schema import (MAX_ANCHORS, MAX_MAX_WIDTH, MAX_PROMPTS, MAX_ROUND_NOTES, MAX_VIEWS, MIN_MAX_WIDTH, Anchor, AnchorNote, Answer,
                                           Label, Prompt, RoundContext, Uuid)


class LiveBody(_Body):

    summary: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    html: Page
    viewport: Optional[int] = Field(default=None, ge=240, le=2560)
    views: List[ExtraView] = Field(default_factory=list, max_length=MAX_VIEWS - 1)
    prompts: List[Prompt] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchors: List[Anchor] = Field(default_factory=list, max_length=MAX_ANCHORS)
    max_width: Optional[int] = Field(default=None, ge=MIN_MAX_WIDTH, le=MAX_MAX_WIDTH)
    inline_picks: Optional[bool] = None
    open: bool = True


class LiveCreateBody(LookChecked, LiveBody):

    slug_name: SlugName
    title: Label
    kind: str = Field(default="mockup", pattern=r"^(mockup|flowchart|copy|other)$")
    task: TaskRef
    viewport: int = Field(ge=240, le=2560)
    color: Optional[str] = None
    icon: Optional[str] = None


class MilestoneBody(_Body):

    name: Optional[Label] = None
    summary: Optional[Annotated[str, StringConstraints(min_length=1, max_length=2000)]] = None
    request_review: bool = True
    base_etag: Optional[Etag] = None


class LiveEndBody(_Body):

    milestone: Optional[Label] = None
    request_review: bool = True


class LiveSendBody(_Body):

    client_round_id: Uuid
    revision: Literal["draft"] = "draft"
    seq: Optional[int] = Field(default=None, ge=1)
    answers: List[Answer] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchor_notes: List[AnchorNote] = Field(default_factory=list, max_length=MAX_ANCHORS)
    note: Annotated[str, StringConstraints(max_length=MAX_ROUND_NOTES)] = ""
    context: RoundContext = Field(default_factory=RoundContext)
