"""The gate that must pass before a one-shot body is pasted into a pane.

WHY A GATE EXISTS AT ALL, and why it is three POSITIVE signals rather than
the absence of a bad one.

``tmux`` only wraps a paste in bracketed-paste markers "if the application
has requested bracketed paste mode" (``man tmux`` 3.6a, ``paste-buffer
-p``), and when it has not, tmux replaces every line ending in the buffer
with a CARRIAGE RETURN. A carriage return at a shell prompt is not a
newline, it is EXECUTE. So the exact same ``load-buffer`` plus
``paste-buffer`` that types a paragraph into a running agent will run a
skill's text line by line as shell commands if the pane happens to be
sitting at a prompt, or answer an open dialog with whatever the first line
happens to be. tmux exposes no format string for the pane's bracketed-paste
mode, so the code cannot ask; it has to establish that the pane is an agent
by other means before it pastes anything at all.

THE THREE SIGNALS, AND WHY NO ONE OF THEM WOULD DO ALONE.

       a bare interactive pane   ->  ``zsh``
       a pane running ``codex``  ->  ``node``
       a pane running ``claude`` ->  ``2.1.266``  (the version, not a name)

   WHERE THAT STATE COMES FROM, AND WHY IT IS NOT A CACHED FLAG. This
   rung used to read ``SessionActivityTracker.permission_open``, a flag
   the deleted hook stream was the only writer of. With the hooks gone
   NOTHING set it True, so the rung answered "no dialog" for every
   session on every call: an INERT GATE, which is worse than no gate
   because it reads as protection. The state now comes from the passive
   four-tier resolver (``src/core/attention/resolve.py``: registry,
   transcript tail, pane, tmux) through the same per-session path
   ``/sessions/list`` paints from, so this gate and the status light can
   never disagree about one session.

   THE FIVE STATES THAT PASS ARE LISTED, NOT DERIVED BY EXCLUSION
   (:data:`PASTE_SAFE_STATUSES`): ``idle``, ``finished_unread``,
   ``working``, ``working_subagent`` and ``notice``. Everything else
   refuses, and the three that matter are ``question`` (a dialog or a
   blocking tool is open), ``dead``, and ``unknown``. ``unknown`` IS A
   REAL ANSWER AND IT REFUSES: a state that could not be positively
   confirmed is not a green light. So does a state name this gate does
   not recognise, and so does no state at all.

4. ``startup_gate == 'ready'``. This is a DIFFERENT question from rung 3
   and neither substitutes for the other: the folder-trust dialog runs
   BEFORE claude registers itself, so a pane parked on it has no
   registry record at all and rung 3 cannot see it. Only ``ready``
   passes; ``awaiting_startup_prompt`` and ``unknown`` both refuse.

THE BODY IS A SEPARATE REFUSAL FROM THE PANE. ESC (``0x1b``) is refused
outright rather than stripped, because ESC is the lead byte of every
terminal control sequence: a stripped ESC leaves the rest of the sequence
behind as text, and a body carrying one is not a prompt anyone typed. Every
other C0, C1 and DEL character except newline and tab is stripped and
COUNTED, so the caller is told what was removed rather than silently
handed a different body than it sent. Carriage return is in that stripped
set and that is the point: a lone CR inside the body would be a second
Enter.
"""

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
# could not be read
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
    """The session's live status is not one a body may be pasted into: a status that was not confirmed, not a dialog reading.

    Description: raised by :func:`check_can_paste` for a status outside :data:`PASTE_SAFE_STATUSES`. It keeps the code
        ``pane_dialog_open`` for every caller that only matches the code, and carries the status so the route that
        holds the live pane can ask the SCREEN whether a dialog is open when the status is ``unknown`` (a real answer
        that means "not measured", never a dialog: docs/session-status-model.md).
    Inputs (constructor): status (str | None) - the status that was refused.
    Output: a StatusUnconfirmed carrying ``.status``, ``.code`` and ``.message``.
    Example: StatusUnconfirmed("unknown").status
    """

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
    """Refuse unless all four positive signals say this pane is a live, free agent.

    Description: pure, so the whole rule is testable without tmux, a
        database or a route. Returns None on a pass and raises on every
        refusal, so a caller cannot forget to check a returned verdict.
        Rungs 1 and 2 both answer ``pane_not_an_agent`` because from the
        caller's side they are one question - is there an agent there -
        answered from two sources.

        RUNGS 3 AND 4 FAIL CLOSED. Each one passes on a SHORT LIST of
        positively-confirmed values and refuses everything else,
        including ``None``, including ``unknown``, and including a value
        this gate does not recognise. A state that cannot be positively
        confirmed is not a green light: refusing costs the caller a
        retry, and being wrong presses Enter on somebody's open dialog.
    Inputs:
        pane_current_command: raw ``#{pane_current_command}``, or None
            when the live read did not answer.
        pane_dead: raw ``#{pane_dead}`` ("0" or "1"), or None when
            unread. Only a measured ``"1"`` counts as dead.
        agent_type: ``sessions.agent_type`` from the row, or None.
        activity_status: the session's LIVE resolved attention state, one
            of the eight names in ``src.core.session_status``, as
            ``SessionInfo.activity_status`` carries it. Only the five in
            :data:`PASTE_SAFE_STATUSES` pass.
        startup_gate: ``SessionInfo.startup_gate``. Only
            ``ready`` passes; a pane parked on the folder-trust dialog
            reports ``awaiting_startup_prompt`` and one that could not be
            determined reports ``unknown``, and both refuse.
        foreground_agent_proven: True only when
            ``attention.pane_agent_proof.registered_agent_in_foreground``
            proved a registry-verified claude is the pane's foreground
            job. A launch profile runs claude as a child of ``zsh -c``, so
            the pane's command reads ``zsh`` while claude has the
            terminal; this proof, not the name, passes rung 1 then. It
            passes rung 2 too: claude's own registry record is an agent
            record, so an adopted row with no label is not refused.
    Output: None.
    Raises: OneShotRefused with ``pane_not_an_agent`` or
        ``pane_dialog_open``.
    Example: check_can_paste(pane_current_command='node', pane_dead='0',
        agent_type='codex', activity_status='idle',
        startup_gate='ready')  # returns None
    """
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
