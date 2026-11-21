
from __future__ import annotations

import enum
import re
from typing import Any, Dict, FrozenSet, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SCHEMA_VERSION: int = 1

Src = Literal["transcript", "observed"]
SRC_TRANSCRIPT: Src = "transcript"
SRC_OBSERVED: Src = "observed"

Family = Literal["claude", "codex"]
FAMILY_CLAUDE: Family = "claude"
FAMILY_CODEX: Family = "codex"

THREAD_MAIN: str = "main"
THREAD_SIDE: str = "side"
THREAD_AGENT_PREFIX: str = "agent:"
THREAD_WORKFLOW_PREFIX: str = "wf:"
THREAD_RE = re.compile(r"\A(?:main|side|agent:[^\s:]{1,120}|wf:[^\s:]{1,120})\Z")

FILE_KEY_MAIN: str = "main"

MAX_DATA_STR: int = 120

IDENT_RE = re.compile(r"[A-Za-z0-9_.:/\-]{1,120}")
ISO_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?")


def is_ident(value: Any) -> bool:
    return isinstance(value, str) and IDENT_RE.fullmatch(value) is not None


def is_iso_time(value: Any) -> bool:
    return isinstance(value, str) and ISO_TIME_RE.fullmatch(value) is not None


NO_TURN_BOUND: int = 1 << 62

SERIAL_HASH_PREFIX: str = "sha256:"
SERIAL_ID_CHARS: int = 8


class Kind(str, enum.Enum):

    PROMPT = "prompt"
    COMMAND = "command"
    REPLY = "reply"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    BG_START = "bg_start"
    BG_END = "bg_end"
    WAITING = "waiting"
    WAITING_END = "waiting_end"
    QUEUE = "queue"
    TURN_END = "turn_end"
    COMPACTION = "compaction"
    CONVERSATION_SWITCH = "conversation_switch"
    REWIND = "rewind"
    SUPPRESSED = "suppressed"
    NOTICE = "notice"
    TODO = "todo"
    STATUS = "status"
    LIFECYCLE = "lifecycle"
    UNKNOWN = "unknown"


LEVEL_TALK, LEVEL_WORK, LEVEL_TRACE, LEVEL_RAW = 1, 2, 3, 4

KIND_LEVELS: Mapping[Kind, int] = {
    Kind.PROMPT: LEVEL_TALK, Kind.COMMAND: LEVEL_WORK, Kind.REPLY: LEVEL_TALK, Kind.THINKING: LEVEL_TRACE,
    Kind.TOOL_CALL: LEVEL_TRACE, Kind.TOOL_RESULT: LEVEL_TRACE, Kind.SUBAGENT_START: LEVEL_WORK,
    Kind.SUBAGENT_END: LEVEL_WORK, Kind.BG_START: LEVEL_WORK, Kind.BG_END: LEVEL_WORK, Kind.WAITING: LEVEL_TALK,
    Kind.WAITING_END: LEVEL_TALK, Kind.QUEUE: LEVEL_TRACE, Kind.TURN_END: LEVEL_WORK, Kind.COMPACTION: LEVEL_WORK,
    Kind.CONVERSATION_SWITCH: LEVEL_WORK, Kind.REWIND: LEVEL_WORK, Kind.SUPPRESSED: LEVEL_TRACE,
    Kind.NOTICE: LEVEL_TRACE, Kind.TODO: LEVEL_WORK, Kind.STATUS: LEVEL_RAW, Kind.LIFECYCLE: LEVEL_WORK,
    Kind.UNKNOWN: LEVEL_RAW,
}

TALK_NOTICES: FrozenSet[str] = frozenset({"api_error", "usage_limit"})

KIND_DATA_KEYS: Mapping[Kind, FrozenSet[str]] = {
    Kind.PROMPT: frozenset({"origin", "plain", "wrapped", "chars", "attachments", "bytes", "oversize"}),
    Kind.COMMAND: frozenset({"name", "part", "via"}),
    Kind.REPLY: frozenset({"model", "final", "chars"}),
    Kind.THINKING: frozenset({"chars"}),
    Kind.TOOL_CALL: frozenset({"tool_use_id", "name"}),
    Kind.TOOL_RESULT: frozenset({"tool_use_id", "name", "ok", "bytes", "task_id", "oversize"}),
    Kind.SUBAGENT_START: frozenset({"tool_use_id", "agent_id", "type", "background"}),
    Kind.SUBAGENT_END: frozenset({"tool_use_id", "agent_id", "status", "via"}),
    Kind.BG_START: frozenset({"task_id", "tool_use_id", "bg_kind"}),
    Kind.BG_END: frozenset({"task_id", "tool_use_id", "bg_kind", "status", "via"}),
    Kind.WAITING: frozenset({"what", "tool", "fingerprint"}),
    Kind.WAITING_END: frozenset({"answered_by"}),
    Kind.QUEUE: frozenset({"op", "plain", "wrapped", "chars", "command_uuid", "delivery_id"}),
    Kind.TURN_END: frozenset({"via", "end", "duration_ms", "pending_agents", "pending_workflows", "merged"}),
    Kind.COMPACTION: frozenset({"phase", "trigger", "pre_tokens"}),
    Kind.CONVERSATION_SWITCH: frozenset({"from_conv", "to_conv", "how"}),
    Kind.REWIND: frozenset({"fork_uuid", "abandoned_from", "abandoned_to"}),
    Kind.SUPPRESSED: frozenset({"cause"}),
    Kind.NOTICE: frozenset({"what", "subtype", "status", "task_id", "task_type", "http_status", "retry_attempt",
                            "hook", "exit_code"}),
    Kind.TODO: frozenset({"op", "count", "pending", "in_progress", "completed"}),
    Kind.STATUS: frozenset({"state", "tool", "fingerprint"}),
    Kind.LIFECYCLE: frozenset({"milestone"}),
    Kind.UNKNOWN: frozenset({"record_type", "subtype", "attachment_type", "block", "bytes", "oversize"}),
}


class Pos(BaseModel):
    """The cursor of an event: where its line ends in the transcript (plan 1.1).

    Fields: conv (the conversation id), file_key (``main`` or the ``agent_id`` of a sub-agent file), offset (the byte
    offset where the line ends), serial (``transcript_manifest.tail.line_serial`` of that line, the stale-position
    check). Frozen, hashable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    conv: str
    file_key: str = FILE_KEY_MAIN
    offset: int
    serial: str

    @field_validator("offset")
    @classmethod
    def _offset_not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("offset must not be negative")
        return value


class TimelineEvent(BaseModel):
    """One typed event of a session's timeline (plan 1.1). Immutable; ``id`` is derived, never stored.

    The fields are the plan's envelope. ``n`` is the index of the event among those one line produced (usually 0).
    ``data`` is checked against :data:`KIND_DATA_KEYS` and carries no conversation text (module docstring).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    v: int = SCHEMA_VERSION
    pos: Pos
    n: int = 0
    t: Optional[str] = None
    src: Src = SRC_TRANSCRIPT
    family: Family = FAMILY_CLAUDE
    thread: str = THREAD_MAIN
    turn: Optional[int] = None
    parent: Optional[str] = None
    msg: Optional[str] = None
    kind: Kind
    data: Dict[str, Any] = {}

    @model_validator(mode="after")
    def _shape_is_declared_and_holds_no_text(self) -> "TimelineEvent":
        if not THREAD_RE.match(self.thread):
            raise ValueError(f"thread {self.thread!r} is not main, side, agent:<id> or wf:<id>")
        if self.t is not None and not is_iso_time(self.t):
            raise ValueError("t is not an ISO timestamp: a free-text field is never stored")
        allowed = KIND_DATA_KEYS[self.kind]
        extra = sorted(set(self.data) - allowed)
        if extra:
            raise ValueError(f"{self.kind.value} data may not carry {extra}")
        for key, value in self.data.items():
            _check_value(self.kind, key, value)
        return self

    @property
    def id(self) -> str:
        serial = self.pos.serial.removeprefix(SERIAL_HASH_PREFIX)[:SERIAL_ID_CHARS]
        return f"{self.pos.conv}:{self.pos.file_key}:{self.pos.offset}:{self.n}:{serial}"

    @property
    def level(self) -> int:
        return level_of(self.kind, self.data)


def _check_value(kind: Kind, key: str, value: Any) -> None:
    items = value if isinstance(value, list) else [value]
    if isinstance(value, list) and not all(isinstance(item, str) for item in items):
        raise ValueError(f"{kind.value}.{key} is a list that holds more than strings")
    for item in items:
        if not isinstance(item, (str, int, float, bool)):
            raise ValueError(f"{kind.value}.{key} is a {type(item).__name__}: only scalars are stored")
        if isinstance(item, str) and len(item) > MAX_DATA_STR:
            raise ValueError(f"{kind.value}.{key} is {len(item)} characters: text is not stored")


def level_of(kind: Kind, data: Mapping[str, Any]) -> int:
    if kind is Kind.NOTICE and data.get("what") in TALK_NOTICES:
        return LEVEL_TALK
    return KIND_LEVELS[kind]
