
from __future__ import annotations

from dataclasses import dataclass
from contextvars import ContextVar
from typing import Optional

from src.core.session_startup_gate import GATE_READY
from src.core.session_status import (
    KNOWN_SHELL_COMMANDS,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_NOTICE,
    STATUS_WORKING,
    STATUS_WORKING_SUBAGENT,
)

PROMPT_READY_STATUSES: tuple[str, ...] = (STATUS_IDLE, STATUS_FINISHED_UNREAD)

PANE_NOT_AN_AGENT: str = "pane_not_an_agent"
PANE_DIALOG_OPEN: str = "pane_dialog_open"
DIALOG_UNREADABLE: str = "dialog_unreadable"
BODY_HAS_ESCAPE: str = "body_has_escape"
BODY_EMPTY: str = "body_empty"
BODY_TOO_LARGE: str = "body_too_large"
BODY_NOT_UTF8: str = "body_not_utf8"

PASTE_SAFE_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_IDLE,
        STATUS_FINISHED_UNREAD,
        STATUS_WORKING,
        STATUS_WORKING_SUBAGENT,
        STATUS_NOTICE,
    }
)

MAX_BODY_BYTES: int = 64 * 1024

ESCAPE: str = "\x1b"

KEPT_CONTROLS: frozenset[str] = frozenset({"\n", "\t"})


class OneShotRefused(Exception):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CleanBody:

    text: str
    stripped_count: int
    byte_length: int


def is_stripped_control(char: str) -> bool:
    if char in KEPT_CONTROLS:
        return False
    code_point = ord(char)
    return code_point < 0x20 or 0x7F <= code_point <= 0x9F


def sanitize_body(text: str) -> CleanBody:
    try:
        raw_bytes = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise OneShotRefused(
            BODY_NOT_UTF8,
            "the body is not valid utf-8 (it carries an unpaired surrogate), "
            "so it cannot be encoded for the pane",
        )
    if not text.strip():
        raise OneShotRefused(
            BODY_EMPTY, "the body is empty, so there is nothing to paste"
        )
    if raw_bytes > MAX_BODY_BYTES:
        raise OneShotRefused(
            BODY_TOO_LARGE,
            f"the body is {raw_bytes} bytes and the limit is {MAX_BODY_BYTES}",
        )
    if ESCAPE in text:
        raise OneShotRefused(
            BODY_HAS_ESCAPE,
            "the body contains an escape character (0x1b), which starts a "
            "terminal control sequence and is refused rather than stripped",
        )

    kept = [char for char in text if not is_stripped_control(char)]
    cleaned = "".join(kept)
    stripped_count = len(text) - len(kept)
    if not cleaned.strip():
        raise OneShotRefused(
            BODY_EMPTY,
            "the body held nothing but control characters, so there is "
            "nothing left to paste once they are removed",
        )
    return CleanBody(
        text=cleaned,
        stripped_count=stripped_count,
        byte_length=len(cleaned.encode("utf-8")),
    )


def pane_command_is_agent(pane_current_command: Optional[str]) -> bool:
    command = (pane_current_command or "").strip()
    if not command:
        return False
    return command not in KNOWN_SHELL_COMMANDS


QUIET_REFUSALS: ContextVar[bool] = ContextVar("one_shot_quiet_refusals", default=False)


class StatusUnconfirmed(OneShotRefused):

    def __init__(self, status: Optional[str]) -> None:
        super().__init__(
            PANE_DIALOG_OPEN,
            f"this session's live status is {status!r}, which is not "
            "one of the states a body may be pasted into; a paste delivered "
            "into an open dialog would answer it, and a status that could not "
            "be positively confirmed is refused rather than assumed safe",
        )
        self.status = status


def check_can_paste(
    *,
    pane_current_command: Optional[str],
    pane_dead: Optional[str],
    agent_type: Optional[str],
    activity_status: Optional[str],
    startup_gate: Optional[str],
    foreground_agent_proven: bool = False,
) -> None:
    if pane_dead == "1":
        raise OneShotRefused(
            PANE_NOT_AN_AGENT,
            "the pane's process has exited, so there is no agent to paste into",
        )
    if not (pane_command_is_agent(pane_current_command) or foreground_agent_proven):
        raise OneShotRefused(
            PANE_NOT_AN_AGENT,
            "the pane's current command is "
            f"{pane_current_command!r}, which is a shell or could not be "
            "read, and no registered claude is the pane's foreground job; a "
            "paste into a shell prompt would be executed line by line",
        )
    if not ((agent_type or "").strip() or foreground_agent_proven):
        raise OneShotRefused(
            PANE_NOT_AN_AGENT,
            "the session row carries no agent record, so nothing positively "
            "confirms an agent is running in this pane",
        )
    if activity_status not in PASTE_SAFE_STATUSES:
        raise StatusUnconfirmed(activity_status)
    if startup_gate != GATE_READY:
        raise OneShotRefused(
            PANE_DIALOG_OPEN,
            f"this session's startup gate is {startup_gate!r} rather than "
            f"{GATE_READY!r}, so the pane may still be sitting on its "
            "folder-trust prompt, which a paste would answer",
        )
