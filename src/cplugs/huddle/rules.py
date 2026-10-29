
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping, Optional

from src.cplugs.sdk import old_names, work

JOE = "joe"
CLAUDE = "claude"
ACTORS = (JOE, CLAUDE)

OWNER_KEY = "owner"
SWARM_KEY = "swarm"
NUDGE_KEY = "nudge"
CARNIVORE_KEY = "carnivore"

NOT_A_CARD_REFS = ("", "chat")

CLOSED_REF_PREFIX = "closed:"

STATE_REQUEST_TOOL = "task_manager_state_request"

OPEN = "open"
REVIEW = "review"
WAITING = "waiting"
TODO = "todo"
DONE = "done"
STATES = (OPEN, TODO, WAITING, REVIEW, DONE)
APPROVED_STATES = frozenset({DONE})

STATE_ALIASES: Mapping[str, str] = MappingProxyType({
    "approved": DONE,
    "approved_with_note": DONE,
    "waiting_install": WAITING,
    "back_burner": TODO,
    "done_by_claude": REVIEW,
})
old_names.declare(old_names.STATE, list(STATE_ALIASES))
CLAUDE_STATES = tuple(s for s in STATES if s not in APPROVED_STATES)
STATE_ARGS = ("state", "fork_state", "parent_state", "to_state")

ANSWERED_SUPERSEDED = 2

QUESTION = "question"
REPLY = "reply"

KINDS = ("question", "done", "waiting", "info")
NO_KIND = ""

ALL_LIST = work.lists.ALL_LIST

MAX_TEXT = 2000
MAX_NOTE = 4000
MAX_MESSAGE = 4000


class TaskManagerError(Exception):

    code = "task_manager_error"
    status = 400


class TaskManagerInvalid(TaskManagerError):

    code = "task_manager_invalid"
    status = 400


class TaskManagerForbidden(TaskManagerError):

    code = "task_manager_forbidden"
    status = 403


class TaskManagerNotFound(TaskManagerError):

    code = "task_manager_not_found"
    status = 404


class TaskManagerFileRemoved(TaskManagerError):

    code = "task_manager_file_removed"
    status = 409


class TaskManagerNotAttacher(TaskManagerError):

    code = "task_manager_not_attacher"
    status = 403


class TaskManagerFileUnsafe(TaskManagerError):

    code = "task_manager_file_unsafe"
    status = 409


class TaskManagerFileShared(TaskManagerError):

    code = "task_manager_file_shared"
    status = 409


class TaskManagerFileOnBoard(TaskManagerError):

    code = "task_manager_file_on_board"
    status = 409


class TaskManagerBytesNotRemoved(TaskManagerError):

    code = "task_manager_bytes_not_removed"
    status = 503


class TaskManagerStale(TaskManagerError):

    code = "task_manager_stale"
    status = 409

    def __init__(self, message: str, current: Optional[dict] = None) -> None:
        super().__init__(message)
        self.current = current


class TaskManagerNotAllowed(TaskManagerError):

    code = "task_manager_not_allowed"
    status = 409

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class TaskManagerLocked(TaskManagerNotAllowed):

    code = "task_manager_locked"
    status = 409

    def __init__(self, reason: str, message: str, blocking: Mapping[str, Any]) -> None:
        super().__init__(reason, message)
        self.blocking = dict(blocking)


class TaskManagerUseFireAt(TaskManagerNotAllowed):

    code = "task_manager_use_fire_at"
    status = 409

    def __init__(self, fire_at: str) -> None:
        super().__init__("use_fire_at", f"a wait that ends at a known time is a schedule, not a wait: set fire_at {fire_at} on this task "
                         "(task_manager_update with fire_at and state todo) and Carnivore sends it to you then; waiting is for what has no time")
        self.fire_at = fire_at


class TaskManagerAnswered(TaskManagerError):

    code = "task_manager_answered"
    status = 409


def check_actor(actor: str) -> str:
    if actor not in ACTORS:
        raise TaskManagerInvalid(f"unknown actor {actor!r}")
    return actor


def check_list_key(key: object) -> str:
    if not work.lists.is_valid(key):
        raise TaskManagerInvalid("list must be 'all', a project id or agent:<id>")
    return str(key)


def agent_id_of(key: object) -> Optional[int]:
    return work.lists.agent_id_of(key)


def list_order_id(key: str) -> int:
    return work.lists.order_id(key)


def check_kind(value: object) -> str:
    if value == NO_KIND or value in KINDS:
        return str(value)
    raise TaskManagerInvalid(f"kind must be one of {', '.join(KINDS)} (or empty for none)")


def clean_text(value: object, field: str, limit: int, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        raise TaskManagerInvalid(f"{field} must be text")
    text = value.strip()
    if not text and not allow_blank:
        raise TaskManagerInvalid(f"{field} must not be empty")
    if len(text) > limit:
        raise TaskManagerInvalid(f"{field} is over the {limit} character limit")
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise TaskManagerInvalid(f"{field} may not contain control characters")
    return text


def canonical_state(value: Any, *, count: bool = True) -> Any:
    if not isinstance(value, str):
        return value
    current = STATE_ALIASES.get(value, value)
    if count and current != value:
        old_names.note(old_names.STATE, value)
    return current


def canonical_state_args(args: Mapping[str, Any]) -> dict:
    return {k: canonical_state(v) if k in STATE_ARGS else v for k, v in args.items()}


def unchecked_state(claude_done: bool, *, swarm_lane: bool = False) -> str:
    return REVIEW if claude_done and swarm_lane else OPEN


def check_not_swarm_card(actor: str, swarm_ref: str) -> None:
    if actor == CLAUDE and swarm_ref not in NOT_A_CARD_REFS:
        raise TaskManagerForbidden("this card is the owner's to decide; an agent cannot change it")


def next_state(actor: str, current: str, *, approve: Optional[bool], state: Optional[str],
               note: str, claude_done: bool, swarm_lane: bool = False) -> str:
    check_actor(actor)
    state = canonical_state(state)
    if state is not None and state not in STATES:
        raise TaskManagerInvalid(f"state must be one of {', '.join(STATES)}")
    if actor == CLAUDE:
        if approve is not None or (state in APPROVED_STATES):
            raise TaskManagerForbidden("only joe approves an item")
        if state is None:
            return current
        if current in APPROVED_STATES:
            raise TaskManagerForbidden(f"joe approved this item; only joe can change its state now. To ask him to reopen or close it, call {STATE_REQUEST_TOOL} (he approves each request in the approvals inbox)")
        return state
    if approve is not None and state is not None:
        raise TaskManagerInvalid("give approve or state, not both")
    if approve is True:
        return DONE
    if approve is False:
        return unchecked_state(claude_done, swarm_lane=swarm_lane) if current in APPROVED_STATES else current
    if state is not None:
        return state
    return current
