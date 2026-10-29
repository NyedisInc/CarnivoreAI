
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CardHolder(BaseModel):
    """The Swarm agent holding a card (its lease). ``name`` is filled in by core from the agent roster."""

    agent_id: int
    name: Optional[str] = None
    since: Optional[float] = None
    started_at: Optional[float] = None
    beat_at: Optional[float] = None


class CardChildren(BaseModel):
    """Counts of a card's live child cards."""

    total: int = 0
    done: int = 0
    in_review: int = 0


class CardOrigin(BaseModel):
    """Where a card came from: owner, owner_message, agent, spawn, session or before_cards (``ref`` names the source)."""

    kind: str
    ref: str = ""


class CardPaused(BaseModel):
    """A paused card: ``mode`` after_step or now, ``by`` the root card whose pause cascaded here."""

    mode: str
    by: Optional[int] = None
    at: Optional[float] = None


class CardMark(BaseModel):
    """The one current mark on a card (handing_off, stalled, waiting_for_slot, validating, validated, validation_failed)."""

    name: str
    at: Optional[float] = None


class CardPin(BaseModel):
    """A card pinned to an agent and, with ``place``, to its queue place."""

    agent_id: Optional[int] = None
    place: bool = False


class CardView(BaseModel):
    """One card, as ``GET /swarm/cards/{id}`` and every board column answer it."""

    id: int
    list_key: str
    project_id: Optional[int] = None
    title: str
    text: str
    column: str
    state: str
    position: int
    queue_index: Optional[int] = None
    group_id: Optional[int] = None
    holder: Optional[CardHolder] = None
    legacy_claim: Optional[str] = None
    last_holder: Optional[int] = None
    dealt_to: Optional[int] = None
    parent: Optional[int] = None
    lane_role: Optional[str] = None
    children: CardChildren
    origin: CardOrigin
    paused: Optional[CardPaused] = None
    mark: Optional[CardMark] = None
    accepted_at: Optional[float] = None
    report_id: Optional[int] = None
    pin: CardPin
    progress: Optional[int] = None
    result: str = ""
    handoff: str = ""
    how_to_validate: str = ""
    validate_link: str = ""
    proof: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None
    phone_sent_at: Optional[float] = None
    revision: int
    created_at: float
    updated_at: float
    summary: str = ""
    queued: bool = False
    archived_at: Optional[float] = None
    auto_promote: bool = False
    owner_note: str = ""
    stranded: bool = False


class CardRules(BaseModel):
    """A queue's card rules. ``dealing`` None is unset (on until the one-time step stores off)."""

    dealing: Optional[bool] = None
    auto_done: bool = False
    auto_validate: bool = False
    reorder: str = "suggest"
    pace: str = "normal"
    updated_at: Optional[float] = None
    updated_by: str = ""


class CardCounts(BaseModel):
    """How many cards sit in each board column."""

    todo: int = 0
    in_progress: int = 0
    review: int = 0
    done: int = 0


class CardColumns(BaseModel):
    """A lane's cards by column: Todo in queue order, Done the newest ``done_limit``."""

    todo: List[CardView] = []
    in_progress: List[CardView] = []
    review: List[CardView] = []
    done: List[CardView] = []


class CardLane(BaseModel):
    """One queue on the board: a project's, or an ``agent:<id>`` / ``all`` list holding company and SysOp cards."""

    project_id: Optional[int] = None
    list_key: str
    name: str
    rules: CardRules
    counts: CardCounts
    columns: CardColumns


class CardWin(BaseModel):
    """The win number (pick V): cards that passed through Review to Done today, and cards in Review now."""

    through_review_today: int
    in_review: int
    since: float


class CapacityReading(BaseModel):
    """``GET /swarm/cards/capacity``: the capacity governor's inputs. ``null`` is not measured (never zero); a floor true means new deals that need a body wait."""

    cpu_busy_pct: Optional[float] = None
    cpu_floor: bool = False
    usage_max_pct: Optional[float] = None
    usage_floor: bool = False
    usage_account: Optional[str] = None
    usage_window: Optional[str] = None
    live_bodies: int
    cap_total: Optional[int] = None
    cap_per_parent: Optional[int] = None
    at: float


class CardBoard(BaseModel):
    """``GET /swarm/cards/board``: the lanes of one scope, the win number and the capacity reading (null when the app datastore cannot be read)."""

    scope: str
    filter: str
    lanes: List[CardLane]
    win: CardWin
    capacity: Optional[CapacityReading] = None


class _Request(BaseModel):
    """Base of every card request: an unknown field is a 422, never ignored."""

    model_config = ConfigDict(extra="forbid")


class CardCreate(_Request):

    project_id: Optional[int] = Field(None, ge=1)
    list_key: Optional[str] = Field(None, min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=120)
    summary: str = Field(..., min_length=1, max_length=200)
    text: str = Field("", max_length=2000)
    parent: Optional[int] = Field(None, ge=1)
    how_to_validate: str = Field("", max_length=4000)
    before_id: Optional[int] = Field(None, ge=1)


class CardColumnMove(_Request):

    column: Literal["todo", "in_progress", "review", "done"]
    note: Optional[str] = Field(None, max_length=4000)


class CardDeleted(BaseModel):
    """``DELETE /swarm/cards/{id}``: the card is gone for good (its history stays)."""

    id: int
    deleted: bool


class CardFlag(_Request):

    on: bool


class CardDone(_Request):

    expected_revision: Optional[int] = Field(None, ge=0)


class CardEvent(BaseModel):
    """One row of a card's history (``card_events``): when, what (``flow.EVENT_KINDS``), the column move if any, who (``owner``, ``server``, ``auto_done``, ``agent:<id>``)."""

    at: float
    kind: str
    from_col: str
    to_col: str
    by: str
    detail: str


class CardEvents(BaseModel):
    """``GET /swarm/cards/{id}/events``: the card's history, oldest first."""

    card_id: int
    events: List[CardEvent]


class CardWindowEvent(BaseModel):
    """One row of a scope's history window (``card_events``, no ``detail``): which card and queue, when, what, the column move, who."""

    item_id: int
    list_key: str
    at: float
    kind: str
    from_col: str
    to_col: str
    by: str


class CardEventWindow(BaseModel):
    """``GET /swarm/cards/events``: every card event of a scope in ``[since, until)``, oldest first; ``truncated`` when older rows were cut."""

    scope: str
    filter: str
    since: float
    until: float
    events: List[CardWindowEvent]
    truncated: bool


class CardSendBack(_Request):

    note: str = Field(..., min_length=1, max_length=4000)


class CardMove(_Request):

    before_id: Optional[int] = Field(None, ge=1)
    pin_place: bool = False


class CardQueue(_Request):

    reason: str = Field("", max_length=500)


class CardRelease(_Request):

    reason: str = Field("", max_length=500)


class CardPause(_Request):

    mode: str = Field(..., pattern="^(after_step|now)$")


class CardSwap(_Request):

    agent_id: int = Field(..., ge=1)


class CardPinRequest(_Request):

    agent_id: Optional[int] = Field(None, ge=1)
    place: bool = False


class CardPauseResult(BaseModel):

    card: CardView
    cascaded: List[int] = []
    agents: List[int] = []


class CardSuggestionAction(_Request):

    action: str = Field(..., pattern="^(apply|dismiss)$")


class CardSuggestionView(BaseModel):

    id: int
    list_key: str
    card_id: int
    before_id: Optional[int] = None
    by_agent: int
    reason: str
    at: float
    state: str
    card: Optional[CardView] = None


class CardRulesPatch(_Request):

    dealing: Optional[bool] = None
    auto_done: Optional[bool] = None
    auto_validate: Optional[bool] = None
    reorder: Optional[str] = Field(None, pattern="^(suggest|auto)$")
    pace: Optional[str] = Field(None, pattern="^(normal|asap)$")


class CardCapability(BaseModel):
    """What would validate a card now: ``kind`` is ``validator_agent``, ``task_agent`` or ``none`` (the card reads "no proof yet")."""

    kind: str
    label: str = ""


class CardValidation(BaseModel):
    """``GET /swarm/cards/{id}/validation`` and ``POST /swarm/cards/{id}/validate``: the recorded validation and whether one can start.

    ``state`` is none, validating, validated or validation_failed; ``proof`` is the validating agent's own text, null until there is one.
    ``can_validate`` is False with ``reason`` (a refusal code: no_capability, not_in_review, no_project_agent, already_validating) when a start would be refused.
    """

    card_id: int
    state: str
    capability: CardCapability
    agent_id: Optional[int] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    verdict: Optional[str] = None
    proof: Optional[str] = None
    can_validate: bool = False
    reason: Optional[str] = None


class CardGrant(BaseModel):
    """One capacity grant: how many agents ``scope`` (``company:<id>`` or ``project:<id>``) may run. ``slots`` null is a removed grant (the default applies)."""

    scope: str
    slots: Optional[int] = None
    set_by: str
    set_at: float
    reason: str = ""


class CardGrantPut(_Request):

    slots: Optional[int] = Field(..., ge=0, le=20)
    reason: str = Field("", max_length=500)
