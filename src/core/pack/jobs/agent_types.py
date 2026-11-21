
from __future__ import annotations

import hashlib
import json
import shlex
from typing import Any, ClassVar, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, field_validator, model_serializer, model_validator

from src.models.model_ids import is_valid_model_id

CAP_AGENT = "pack.jobs.agent"
CAP_REPLY_DIGEST = "pack.jobs.reply_digest"
CAP_ACCOUNT_IDENTITY = "pack.jobs.account_identity"
DIGEST_PATTERN = r"^[0-9a-f]{8}$"


def digest_of(question: Optional[str]) -> str:
    return hashlib.sha256((question or "").encode()).hexdigest()[:8]

JOB_ID_PATTERN = r"^job_[0-9a-f]{12}$"
ACCOUNT_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
AGENT_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
MODEL_MAX = 64


def valid_model(value: str) -> bool:
    return len(value) <= MODEL_MAX and is_valid_model_id(value)

TASK_MAX = 19000
USAGE_MAX = 10**12
DEFINITION_MAX = 8 * 1024
DEFINITION_QUOTED_MAX = 10000
FAMILIES = ("claude", "codex")
CLAUDE_MODES = ("default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan", "manual")
CODEX_MODES = ("ask", "skip_all")
DEFINITION_KEYS = frozenset({"description", "prompt", "tools", "disallowedTools", "model", "effort"})


def agents_argument(agent_type: str, definition_json: str) -> str:
    return json.dumps({agent_type: json.loads(definition_json)}, separators=(",", ":"))


def definition_fits(agent_type: str, definition_json: str) -> bool:
    return len(shlex.quote(agents_argument(agent_type, definition_json))) <= DEFINITION_QUOTED_MAX


class _Wire(BaseModel):
    """Base of every route body: unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")
    omit_when_none: ClassVar[Tuple[str, ...]] = ()

    @model_serializer(mode="wrap")
    def _omit_phase2(self, handler: SerializerFunctionWrapHandler) -> Any:
        out = handler(self)
        if isinstance(out, dict):
            for name in self.omit_when_none:
                if name in out and out[name] is None:
                    del out[name]
        return out


class UsageTotals(_Wire):

    input_tokens: int = Field(default=0, ge=0, le=USAGE_MAX)
    output_tokens: int = Field(default=0, ge=0, le=USAGE_MAX)
    cache_read_tokens: int = Field(default=0, ge=0, le=USAGE_MAX)
    cache_write_tokens: int = Field(default=0, ge=0, le=USAGE_MAX)
    cost_usd: Optional[float] = Field(default=None, ge=0, le=USAGE_MAX, allow_inf_nan=False)


class AgentSpec(_Wire):

    omit_when_none: ClassVar[Tuple[str, ...]] = ("account_identity",)

    task: str = Field(min_length=1, max_length=TASK_MAX)
    family: Literal["claude", "codex"]
    permission_mode: str = Field(min_length=1, max_length=32)
    agent_type: Optional[str] = Field(default=None, pattern=AGENT_NAME_PATTERN)
    definition_json: Optional[str] = Field(default=None, max_length=DEFINITION_MAX)
    model: Optional[str] = Field(default=None, min_length=1, max_length=MODEL_MAX)
    account_key: Optional[str] = Field(default=None, pattern=ACCOUNT_KEY_PATTERN)
    account_identity: Optional[str] = Field(default=None, max_length=320)

    @field_validator("task")
    @classmethod
    def _task(cls, v: str) -> str:
        if "\0" in v or not v.strip():
            raise ValueError("the task must be text with no NUL")
        return v

    @field_validator("model")
    @classmethod
    def _model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not valid_model(v):
            raise ValueError("the model name is not one this computer will launch with")
        return v

    @field_validator("definition_json")
    @classmethod
    def _definition(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v.encode("utf-8")) > DEFINITION_MAX:
            raise ValueError("the definition is larger than 8 KiB")
        try:
            data = json.loads(v)
        except ValueError as exc:
            raise ValueError("the definition is not JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("the definition must be a JSON object")
        extra = set(data) - DEFINITION_KEYS
        if extra:
            raise ValueError(f"definition keys not allowed: {sorted(extra)[:5]}")
        return v

    @model_validator(mode="after")
    def _facts(self) -> "AgentSpec":
        allowed = CLAUDE_MODES if self.family == "claude" else CODEX_MODES
        if self.permission_mode not in allowed:
            raise ValueError(f"permission_mode for {self.family} must be one of {', '.join(allowed)}")
        if self.definition_json is not None and (self.agent_type is None or self.family != "claude"):
            raise ValueError("a definition needs an agent_type and a claude worker")
        return self


class ReplyBody(_Wire):

    omit_when_none: ClassVar[Tuple[str, ...]] = ("question_digest",)
    job_id: str = Field(pattern=JOB_ID_PATTERN)
    text: str = Field(min_length=1, max_length=8000)
    question_digest: Optional[str] = Field(default=None, pattern=DIGEST_PATTERN)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        if "\0" in v:
            raise ValueError("the reply must not contain NUL")
        return v

