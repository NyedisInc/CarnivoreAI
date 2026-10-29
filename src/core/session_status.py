
from __future__ import annotations

from typing import Optional

STATUS_RUNNING: str = "running"
STATUS_IDLE: str = "idle"
STATUS_DEAD: str = "dead"
STATUS_UNKNOWN: str = "unknown"

ALL_STATUSES: frozenset[str] = frozenset(
    {STATUS_RUNNING, STATUS_IDLE, STATUS_DEAD, STATUS_UNKNOWN}
)


STATUS_QUESTION: str = "question"

STATUS_NOTICE: str = "notice"

STATUS_WORKING: str = "working"

STATUS_WORKING_SUBAGENT: str = "working_subagent"

STATUS_FINISHED_UNREAD: str = "finished_unread"

ALL_ACTIVITY_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_DEAD,
        STATUS_QUESTION,
        STATUS_NOTICE,
        STATUS_WORKING,
        STATUS_WORKING_SUBAGENT,
        STATUS_FINISHED_UNREAD,
        STATUS_IDLE,
        STATUS_UNKNOWN,
    }
)

ACTIVITY_STATUS_PRIORITY: tuple[str, ...] = (
    STATUS_DEAD,
    STATUS_QUESTION,
    STATUS_NOTICE,
    STATUS_WORKING_SUBAGENT,
    STATUS_WORKING,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_UNKNOWN,
)



READ_STATE_PAIR: tuple[str, str] = (STATUS_IDLE, STATUS_FINISHED_UNREAD)


def derive_read_state(state: Optional[str], *, unread: bool) -> Optional[str]:
    """Project a session's resting state through its unread flag.

    Description: THE ONE PLACE ``finished_unread`` and ``idle`` are told
        apart, for every source of a status - the hook tracker, the tmux
        fallback, the durable row seed and the transcript ladder all end
        here, and so does the listing that assembles them. Pure, total
        and idempotent: applying it twice with the same flag is applying
        it once, and every state outside ``READ_STATE_PAIR`` is returned
        untouched, so a caller may run it over any status without having
        to know which ones it concerns.

        THE FLAG IS THE FACT AND THE STATE IS THE VIEW OF IT. The unread
        flag is durable, keyed on the tmux instance and owned by
        ``UnreadStore``; ``finished_unread`` is a rendering of the pair
        (at rest, not yet seen). So this function never writes a flag and
        never reads one of its own - the caller supplies the flag it
        measured, and the answer is a function of that measurement alone.
        Write paths use it with ``unread=False`` to store the BASE state,
        which is why ``sessions.activity_state`` no longer bakes a read
        verdict into a column that cannot be updated when the flag moves.
    Inputs:
        state: an activity status, or None when nothing was resolved.
            Any value outside ``READ_STATE_PAIR`` is returned unchanged,
            including None - a state nobody measured is not made into a
            rest claim by a flag.
        unread: the session's persisted unread flag, as MEASURED by the
            caller. Keyword-only so no call site can pass it positionally
            and mean something else.
    Output:
        str | None: ``finished_unread`` when the session is at rest and
            unread, ``idle`` when it is at rest and read, and the input
            unchanged otherwise.
    Example:
        >>> derive_read_state(STATUS_FINISHED_UNREAD, unread=False)
        'idle'
        >>> derive_read_state(STATUS_IDLE, unread=True)
        'finished_unread'
        >>> derive_read_state(STATUS_WORKING, unread=True)
        'working'
        >>> derive_read_state(None, unread=True) is None
        True
    """
    if state not in READ_STATE_PAIR:
        return state
    return STATUS_FINISHED_UNREAD if unread else STATUS_IDLE


KNOWN_SHELL_COMMANDS: frozenset[str] = frozenset(
    {"zsh", "bash", "sh", "dash", "ksh", "fish", "tcsh", "csh"}
)


def resolve_pane_status(
    pane_dead: Optional[str], pane_current_command: Optional[str]
) -> str:
    """Classify a tmux pane's activity state from its raw format-string values.

    Description: Maps the two tmux pane-format values callers already query
        (``#{pane_dead}`` and ``#{pane_current_command}``) onto one of the
        four states this app reports. Pure function, no I/O - callers do the
        tmux query, this does the classification, so the rule is testable
        without a real tmux binary.

    Inputs:
        pane_dead: Raw ``#{pane_dead}`` value ("0" or "1"), or None if the
            query failed / the pane could not be found.
        pane_current_command: Raw ``#{pane_current_command}`` value (e.g.
            "zsh", "claude", "node"), or None if the query failed.

    Output:
        str: One of ``STATUS_RUNNING``, ``STATUS_IDLE``, ``STATUS_DEAD``,
            ``STATUS_UNKNOWN``.

    Example:
        >>> resolve_pane_status("0", "zsh")
        'idle'
        >>> resolve_pane_status("0", "claude")
        'running'
        >>> resolve_pane_status("1", "zsh")
        'dead'
        >>> resolve_pane_status(None, None)
        'unknown'
    """
    if pane_dead is None or pane_current_command is None:
        return STATUS_UNKNOWN

    if pane_dead.strip() == "1":
        return STATUS_DEAD

    cmd = pane_current_command.strip().lower()
    if not cmd:
        return STATUS_UNKNOWN

    if cmd in KNOWN_SHELL_COMMANDS:
        return STATUS_IDLE

    return STATUS_RUNNING


# could not

LIVENESS_LIVE: str = "live"

# the session is gone
LIVENESS_GONE: str = "gone"

LIVENESS_UNKNOWN: str = "unknown"


def resolve_listing_liveness(
    exists: Optional[bool], pane_status: Optional[str]
) -> str:
    """Decide whether a session belongs in the running list.

    Description: Combines the backend's EXISTENCE answer with tmux's
        pane-level LIVENESS answer into one three-valued verdict. Pure
        function, no I/O, so the rule is testable without a tmux binary.
        Callers pass the pane status they already hold from the bulk
        ``list_pane_status_all()`` probe - this adds no subprocess call.

    Inputs:
        exists: The backend's own existence answer (``is_alive()``), or
            None when that could not be determined. For tmux this is
            ``has-session``, which says the session EXISTS and says
            nothing about whether its pane still has a live process.
        pane_status: A ``resolve_pane_status()`` value for this session's
            pane, or None when pane introspection does not APPLY to this
            backend at all (PTYBackend has no pane; there, existence of
            the child process genuinely is liveness). None means "not
            applicable", which is different from ``STATUS_UNKNOWN``,
            which means "asked, and could not tell".

    Output:
        str: ``LIVENESS_LIVE``, ``LIVENESS_GONE`` or ``LIVENESS_UNKNOWN``.

    Example:
        >>> resolve_listing_liveness(True, STATUS_DEAD)
        'gone'
        >>> resolve_listing_liveness(True, STATUS_IDLE)
        'live'
        >>> resolve_listing_liveness(True, STATUS_UNKNOWN)
        'unknown'
        >>> resolve_listing_liveness(None, STATUS_IDLE)
        'unknown'
    """
    if exists is None:
        return LIVENESS_UNKNOWN
    if not exists:
        return LIVENESS_GONE
    if pane_status is None:
        return LIVENESS_LIVE
    if pane_status == STATUS_DEAD:
        return LIVENESS_GONE
    if pane_status == STATUS_UNKNOWN:
        # could not
        return LIVENESS_UNKNOWN
    return LIVENESS_LIVE
