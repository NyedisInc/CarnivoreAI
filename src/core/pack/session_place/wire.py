
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.pack.jobs.agent_types import ACCOUNT_KEY_PATTERN
from src.models.model_ids import is_valid_model_id

CREATE_PATH = "/federation/pack/sessions/create"
HEX32 = r"^[0-9a-f]{32}$"
HEX40 = r"^[0-9a-f]{40}$"
BRANCH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/@+-]*$"


class PeerCreateBody(BaseModel):
    """The home's create request. ``request_id`` makes a retry answer the session already made. Example: PeerCreateBody(request_id="a"*32, ...)."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=HEX32)
    project_uid: str = Field(min_length=1, max_length=64)
    home_head: str = Field(pattern=HEX40)
    branch: str = Field(min_length=1, max_length=200, pattern=BRANCH_PATTERN)
    family: Literal["claude", "codex", "shell"] = "claude"
    profile_name: Optional[str] = Field(default=None, max_length=120)
    posture: Literal["ask", "accept_edits", "skip_all", "unknown"] = "unknown"
    model: Optional[str] = Field(default=None, max_length=64)
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = None
    account_key: Optional[str] = Field(default=None, pattern=ACCOUNT_KEY_PATTERN)
    label: str = Field(default="", max_length=120)
    cols: Optional[int] = Field(default=None, ge=1, le=1000)
    rows: Optional[int] = Field(default=None, ge=1, le=1000)

    @field_validator("branch")
    @classmethod
    def _branch_ok(cls, value: str) -> str:
        if ".." in value or value.endswith((".", "/", ".lock")) or "//" in value or "/." in value or "@{" in value:
            raise ValueError("not a branch name")
        return value

    @field_validator("model")
    @classmethod
    def _model_ok(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_valid_model_id(value):
            raise ValueError("not a model id")
        return value


class PeerCreateAnswer(BaseModel):
    """What the computer answers: the session it made (or made before, for the same request id). Every string is capped by the reader (H4)."""

    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(max_length=200)
    session_uuid: Optional[str] = Field(default=None, max_length=64)
    tmux_name: str = Field(min_length=1, max_length=200)
    epoch: Optional[int] = None
    working_dir: str = Field(default="", max_length=4096)
    account_label: str = Field(default="", max_length=400)
    account_how: str = Field(default="", max_length=64)
    profile_used: str = Field(default="", max_length=400)
    copy_note: Optional[str] = Field(default=None, max_length=400)
