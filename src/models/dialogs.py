
from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ACTION_BODY_MAX_CHARS: int = 130_000
OTHER_MAX_CHARS: int = 2000
HEX64: str = r"^[0-9a-f]{64}$"


def is_plain_line(text: str) -> bool:
    return not any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in text)


class AnswerChoice(BaseModel):
    """Exactly one of: ``option`` (a label), ``options`` (labels, multi-select),
    ``other`` (free text, single line), ``dismiss`` (true), ``plain`` ("yes" | "no": the permission
    prompt's plain yes or its decline, read off the FRESH pane by label, never "Yes, and ...").

    Example: {"option": "Blue"}   {"options": ["Cheese", "Ham"]}   {"dismiss": true}   {"plain": "yes"}
    """

    model_config = ConfigDict(extra="forbid")

    option: Optional[str] = Field(default=None, min_length=1, max_length=500)
    options: Optional[List[str]] = Field(default=None, max_length=50)
    other: Optional[str] = Field(default=None, min_length=1, max_length=OTHER_MAX_CHARS)
    dismiss: Optional[bool] = None
    plain: Optional[Literal["yes", "no"]] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "AnswerChoice":
        given = [k for k in ("option", "options", "other", "dismiss", "plain") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of option, options, other, dismiss, plain")
        if self.dismiss is False:
            raise ValueError("dismiss must be true")
        texts = [self.other] if self.other is not None else []
        texts += ([self.option] if self.option is not None else []) + list(self.options or ())
        if not all(is_plain_line(text) for text in texts):
            raise ValueError("other and option labels must be a single line of plain text")
        return self


class DialogAnswerRequest(BaseModel):
    """``POST /sessions/{id}/dialog/answer`` body."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(pattern=HEX64)
    choice: AnswerChoice
    source: Optional[Literal["owner_banner"]] = None


class DialogAnswerResponse(BaseModel):
    """The dialog that was answered."""

    answered: bool = True
    kind: str
    fingerprint: str


class DialogResponse(BaseModel):
    """``GET /sessions/{id}/dialog``: the extracted dialog or null."""

    dialog: Optional[Dict[str, Any]] = None


class ApprovalItem(BaseModel):
    """One thing waiting on the owner, from any provider (``GET /api/v1/approvals``).

    ``source`` is ``dialog`` (an agent's open dialog), ``agent_action`` (an MCP gate) or
    ``startup_prompt`` (a session parked on a startup screen whose options could not be read:
    read-only, ``kind`` names the screen, ``body`` is the redacted screen text, no rows; Task Manager
    item 63). A startup screen whose options WERE read is a ``dialog`` item with ``startup_kind``.
    ``host`` is ``local`` or a peer host key; for a peer's item ``session_id`` is the
    ``remote:<peer key>:<tmux name>`` wire id the dialog routes forward on.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(max_length=400)
    source: str = Field(max_length=32)
    host: str = Field(default="local", max_length=200)
    host_label: Optional[str] = Field(default=None, max_length=200)
    session_id: str = Field(max_length=400)
    session_name: Optional[str] = Field(default=None, max_length=400)
    tmux_session: Optional[str] = Field(default=None, max_length=400)
    project: Optional[str] = Field(default=None, max_length=400)
    family: Optional[str] = Field(default=None, max_length=32)
    kind: str = Field(max_length=64)
    question: str = Field(default="", max_length=4000)
    body: Optional[str] = Field(default=None, max_length=ACTION_BODY_MAX_CHARS)
    options: List[str] = Field(default_factory=list, max_length=50)
    rows: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)
    multi_select: bool = False
    has_other: bool = False
    fingerprint: str = Field(default="", max_length=128)
    plain_yes: Optional[str] = Field(default=None, max_length=500)
    plain_no: Optional[str] = Field(default=None, max_length=500)
    startup_kind: Optional[str] = Field(default=None, max_length=64)
    question_index: Optional[int] = None
    question_total: Optional[int] = None
    tabs: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)
    questions: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    questions_fingerprint: Optional[str] = Field(default=None, max_length=128)
    questions_state: Optional[str] = Field(default=None, max_length=32)
    caller: Optional[str] = Field(default=None, max_length=400)
    action: Optional[str] = Field(default=None, max_length=64)
    external_client: Optional[str] = Field(default=None, max_length=200)
    args: Optional[Dict[str, Any]] = None
    summary: Optional[str] = Field(default=None, max_length=1000)
    created_at: Optional[str] = Field(default=None, max_length=64)
    confirm_text: Optional[str] = Field(default=None, max_length=1000)
    display: Optional[Dict[str, Any]] = None
    origin_install_id: Optional[str] = Field(default=None, max_length=200)


class ApprovalsResponse(BaseModel):
    """``GET /api/v1/approvals``: every open item and the change counter."""

    items: List[ApprovalItem] = Field(default_factory=list)
    version: int = 0


class QuestionAnswerBody(BaseModel):
    """One question's answer in a batch: ``option`` (single-select label), ``options`` (multi-select labels),
    ``other`` (one line of free text), ``notes`` (a preview question's per-question notes).

    Example: {"option": "Blue"}   {"options": ["Cheese"], "other": "Corn"}   {"option": "List", "notes": "dense"}
    """

    model_config = ConfigDict(extra="forbid")

    option: Optional[str] = Field(default=None, min_length=1, max_length=500)
    options: Optional[List[Annotated[str, StringConstraints(min_length=1, max_length=500)]]] = Field(default=None, max_length=50)
    other: Optional[str] = Field(default=None, min_length=1, max_length=OTHER_MAX_CHARS)
    notes: Optional[str] = Field(default=None, min_length=1, max_length=OTHER_MAX_CHARS)

    @model_validator(mode="after")
    def _plain_text(self) -> "QuestionAnswerBody":
        for text in (self.other, self.notes):
            if text is not None and not is_plain_line(text):
                raise ValueError("other and notes must be a single line of plain text")
        for label in ([self.option] if self.option is not None else []) + list(self.options or ()):
            if not is_plain_line(label):
                raise ValueError("option labels must be a single line of plain text")
        return self


class QuestionsAnswerRequest(BaseModel):
    """``POST /sessions/{id}/dialog/answer-all`` body: the ask the caller saw and one answer per question, in order."""

    model_config = ConfigDict(extra="forbid")

    questions_fingerprint: str = Field(pattern=HEX64)
    answers: List[QuestionAnswerBody] = Field(min_length=1, max_length=8)
    source: Optional[Literal["owner_banner"]] = None


class QuestionsAnswerResponse(BaseModel):
    """The ask that was answered: how many questions, and whether it went through the review screen."""

    answered: bool = True
    count: int
    via: str
    questions_fingerprint: str
