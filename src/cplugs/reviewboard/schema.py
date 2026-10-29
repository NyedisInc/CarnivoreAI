
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, ClassVar, Dict, FrozenSet, List, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.cplugs.reviewboard.layers.base import ItemId, SidecarModel
from src.cplugs.reviewboard.layers.models import Layer

SCHEMA_ID = "carnivore.reviewboard.sidecar"
SCHEMA_VERSION = 2
BASE_SCHEMA_VERSION = 1
MAX_VIEW_BYTES = 2 * 1024 * 1024
MAX_TEXT = 4000
MAX_ROUND_NOTES = 8000
MAX_PROMPTS = 40
MAX_OPTIONS = 12
MAX_VIEWS = 7
MIN_MAX_WIDTH = 480
MAX_MAX_WIDTH = 2400
MAX_ANCHORS = 60
MAX_REVISIONS = 9999
MAX_ROUNDS = 9999
MAX_LIVE_SENDS = 20
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_SAVES = 200
MAX_DIFF_PATHS = 50
MAX_EXT_DEPTH = 32

Slug = Annotated[str, StringConstraints(pattern=r"^[0-9]{8}-[a-z0-9-]{1,48}$")]
ViewId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,23}$")]
ExtId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]{1,23}$")]
ActorName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]
RevisionId = Annotated[str, StringConstraints(pattern=r"^r[1-9][0-9]*$")]
RoundId = Annotated[str, StringConstraints(pattern=r"^n[1-9][0-9]*$")]
Computer = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
GithubIssue = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}/[A-Za-z0-9_.-]{1,100}#[1-9][0-9]{0,8}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,40}$")]
Uuid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
ViewFile = Annotated[str, StringConstraints(pattern=r"^r[0-9]{3,4}(--[a-z][a-z0-9-]{0,23})?\.html$")]
DraftFile = Annotated[str, StringConstraints(pattern=r"^draft(--[a-z][a-z0-9-]{0,23})?\.html$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=120)]
TIME_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"


def _real_instant(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value


Time = Annotated[str, StringConstraints(pattern=TIME_PATTERN), AfterValidator(_real_instant)]


def _nesting(value: Any) -> int:
    deepest, stack = 0, [(value, 0)]
    while stack:
        node, depth = stack.pop()
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else None
        if children is not None:
            deepest = max(deepest, depth + 1)
            stack.extend((child, depth + 1) for child in children)
    return deepest


class ExtBlock(BaseModel):
    """One extension's block under ``ext``: a version ``v`` and anything else the extension keeps (kept as written)."""

    model_config = ConfigDict(extra="allow")
    v: int = Field(ge=1)

    @model_validator(mode="after")
    def _shallow_enough(self) -> "ExtBlock":
        if _nesting(self.model_extra or {}) > MAX_EXT_DEPTH:
            raise ValueError(f"an extension block may nest at most {MAX_EXT_DEPTH} levels")
        return self


Ext = Dict[ExtId, ExtBlock]


def _json_object(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("a payload is a JSON object")
    try:
        size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"a payload is plain JSON data ({exc})") from exc
    if size > MAX_PAYLOAD_BYTES:
        raise ValueError(f"a payload is at most {MAX_PAYLOAD_BYTES} bytes; this one is {size}")
    if _nesting(value) > MAX_EXT_DEPTH:
        raise ValueError(f"a payload nests at most {MAX_EXT_DEPTH} levels")
    return value


Payload = Annotated[Dict[str, Any], AfterValidator(_json_object)]
DiffPath = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class Actor(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"session", "label"})
    actor: ActorName
    session: Optional[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = None
    label: Optional[Label] = None


class Board(SidecarModel):

    slug: Slug
    title: Label
    kind: Literal["mockup", "flowchart", "copy", "other"]
    created_at: Time
    created_by: Actor


class TaskLinkChange(SidecarModel):

    item_id: int = Field(ge=1)
    computer: Optional[Computer] = None
    from_item_id: Optional[int] = Field(default=None, ge=1, alias="from")
    at: Time
    by: ActorName
    note: Optional[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = None


class TaskLink(SidecarModel):

    item_id: int = Field(ge=1)
    list_: Optional[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(default=None, alias="list")
    computer: Optional[Computer] = None
    github_issue: Optional[GithubIssue] = None
    title_at_link: Optional[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = None
    linked_at: Time
    history: List[TaskLinkChange] = Field(default_factory=list)


class View(SidecarModel):

    id: ViewId
    label: Label
    file: ViewFile
    sha256: Sha256
    bytes: int = Field(ge=1, le=MAX_VIEW_BYTES)


class Option(SidecarModel):

    id: ItemId
    label: Label


class Prompt(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"options", "anchor"})
    id: ItemId
    kind: Literal["choice", "multi", "check", "question"]
    label: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    options: Optional[List[Option]] = Field(default=None, max_length=MAX_OPTIONS)
    anchor: Optional[ItemId] = None


class Anchor(SidecarModel):

    id: ItemId
    label: Label


class Save(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"note"})
    n: int = Field(ge=1)
    at: Time
    payload: Payload
    note: Optional[Annotated[str, StringConstraints(min_length=1, max_length=MAX_TEXT)]] = None


class PayloadDraft(SidecarModel):

    at: Time
    payload: Payload


class PayloadDiff(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"previous"})
    previous: Optional[RoundId] = None
    added: List[DiffPath] = Field(default_factory=list, max_length=MAX_DIFF_PATHS)
    removed: List[DiffPath] = Field(default_factory=list, max_length=MAX_DIFF_PATHS)
    changed: List[DiffPath] = Field(default_factory=list, max_length=MAX_DIFF_PATHS)
    more: int = Field(default=0, ge=0)


class Revision(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"source_commit", "payload_mode", "layer", "max_width", "milestone", "inline_picks", "saves", "draft", "ext"})
    id: RevisionId
    n: int = Field(ge=1)
    created_at: Time
    by: Actor
    summary: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    answers_round: Optional[RoundId] = None
    source_commit: Optional[Commit] = None
    viewport: int = Field(ge=240, le=2560)
    views: List[View] = Field(min_length=1, max_length=MAX_VIEWS)
    prompts: List[Prompt] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchors: List[Anchor] = Field(default_factory=list, max_length=MAX_ANCHORS)
    payload_mode: Optional[bool] = None
    layer: Optional[Layer] = None
    max_width: Optional[int] = Field(default=None, ge=MIN_MAX_WIDTH, le=MAX_MAX_WIDTH)
    milestone: Optional[Label] = None
    inline_picks: Optional[bool] = None
    saves: Optional[List[Save]] = Field(default=None, max_length=MAX_SAVES)
    draft: Optional[PayloadDraft] = None
    ext: Ext = Field(default_factory=dict)


class RoundContext(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"theme", "width", "fit", "view"})
    theme: Optional[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = None
    width: Optional[int] = Field(default=None, ge=1, le=10000)
    fit: Optional[Literal["actual", "fit"]] = None
    view: Optional[ViewId] = None


class Answer(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"options", "checked", "text"})
    prompt: ItemId
    options: Optional[List[ItemId]] = Field(default=None, max_length=MAX_OPTIONS)
    checked: Optional[bool] = None
    text: Optional[Annotated[str, StringConstraints(max_length=MAX_TEXT)]] = None
    note: Annotated[str, StringConstraints(max_length=MAX_TEXT)] = ""


class AnchorNote(SidecarModel):

    anchor: ItemId
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_TEXT)]


class Delivery(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"item_id", "message_id", "at", "reason"})
    state: Literal["pending", "posted", "undelivered"]
    item_id: Optional[int] = Field(default=None, ge=1)
    message_id: Optional[int] = Field(default=None, ge=1)
    at: Optional[Time] = None
    reason: Optional[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = None


class Round(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"payload", "save", "diff", "ext"})
    KEEP_EMPTY: ClassVar[FrozenSet[str]] = frozenset({"payload"})
    id: RoundId
    n: int = Field(ge=1)
    revision: RevisionId
    client_round_id: Uuid
    sent_at: Time
    by: ActorName
    context: RoundContext = Field(default_factory=RoundContext)
    answers: List[Answer] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchor_notes: List[AnchorNote] = Field(default_factory=list, max_length=MAX_ANCHORS)
    note: Annotated[str, StringConstraints(max_length=MAX_ROUND_NOTES)] = ""
    unanswered: List[ItemId] = Field(default_factory=list, max_length=MAX_PROMPTS)
    payload: Optional[Payload] = None
    save: Optional[int] = Field(default=None, ge=1)
    diff: Optional[PayloadDiff] = None
    delivery: Delivery
    ext: Ext = Field(default_factory=dict)


class DraftView(SidecarModel):

    id: ViewId
    label: Label
    file: DraftFile
    sha256: Sha256
    bytes: int = Field(ge=1, le=MAX_VIEW_BYTES)


class LiveDraft(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"max_width", "inline_picks"})
    seq: int = Field(ge=1)
    updated_at: Time
    summary: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    viewport: int = Field(ge=240, le=2560)
    views: List[DraftView] = Field(min_length=1, max_length=MAX_VIEWS)
    prompts: List[Prompt] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchors: List[Anchor] = Field(default_factory=list, max_length=MAX_ANCHORS)
    max_width: Optional[int] = Field(default=None, ge=MIN_MAX_WIDTH, le=MAX_MAX_WIDTH)
    inline_picks: Optional[bool] = None

    @property
    def id(self) -> str:
        return "draft"


class LiveDelivery(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"via", "reason"})
    state: Literal["pending", "told", "posted", "undelivered"]
    via: Optional[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = None
    reason: Optional[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = None


class LiveSend(SidecarModel):

    n: int = Field(ge=1)
    at: Time
    seq: int = Field(ge=1)
    client_round_id: Uuid
    context: RoundContext = Field(default_factory=RoundContext)
    answers: List[Answer] = Field(default_factory=list, max_length=MAX_PROMPTS)
    anchor_notes: List[AnchorNote] = Field(default_factory=list, max_length=MAX_ANCHORS)
    note: Annotated[str, StringConstraints(max_length=MAX_ROUND_NOTES)] = ""
    unanswered: List[ItemId] = Field(default_factory=list, max_length=MAX_PROMPTS)
    delivery: LiveDelivery


class Live(SidecarModel):

    started_at: Time
    by: Actor
    draft: LiveDraft
    sends: List[LiveSend] = Field(default_factory=list, max_length=MAX_LIVE_SENDS)
    sends_total: int = Field(default=0, ge=0)


class Sidecar(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"live"})
    schema_: Literal["carnivore.reviewboard.sidecar"] = Field(alias="schema")
    schema_version: Literal[1, 2]
    board: Board
    task: Optional[TaskLink]
    revisions: List[Revision] = Field(default_factory=list, max_length=MAX_REVISIONS)
    rounds: List[Round] = Field(default_factory=list, max_length=MAX_ROUNDS)
    live: Optional[Live] = None
    ext: Ext = Field(default_factory=dict)
