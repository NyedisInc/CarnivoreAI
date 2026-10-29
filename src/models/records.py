
from typing import Optional, List
from pydantic import BaseModel, Field

from src.models.sessions import ScheduledMark




class SessionRecord(BaseModel):
    """One row of the ``sessions`` table, as the home screen reads it.

    Every field that can be unmeasured is nullable or carries an explicit
    unknown value. In particular ``lifecycle`` has THREE values and
    ``unknown`` is not a flavour of ``stopped``: it means the tmux probe
    did not answer, and a row in that state offers no lifecycle actions.
    """

    session_uuid: str = Field(..., description="Stable external identity")
    origin: str = Field(
        ...,
        description=(
            "'created' | 'adopted' | 'observed'. The first two are OURS; "
            "'observed' is the only value that renders as external"
        ),
    )
    owned: bool = Field(
        ...,
        description="True when origin is 'created' or 'adopted' (design 4.6)",
    )
    adopted_at: Optional[str] = Field(
        default=None,
        description="When this session was first claimed. Never rewritten",
    )
    tmux_socket: Optional[str] = Field(default=None)
    tmux_name: Optional[str] = Field(default=None)
    tmux_created_epoch: Optional[int] = Field(
        default=None,
        description=(
            "tmux #{session_created}. With socket and name this is the "
            "INSTANCE identity; the name alone is not an identity"
        ),
    )
    lifecycle: str = Field(
        ...,
        description="'running' | 'stopped' | 'unknown' - see design 4.2",
    )
    lifecycle_checked_at: Optional[str] = Field(default=None)
    lifecycle_source: Optional[str] = Field(default=None)
    project_id: Optional[int] = Field(default=None)
    project_name: Optional[str] = Field(
        default=None,
        description=(
            "The project's display_name, joined in by "
            "session_store.list_sessions (issue #608). None means "
            "project_id is itself None, or its project row was deleted - "
            "never a guess from working_dir. An ASLEEP row (no live tmux "
            "pane) has no other source for this name, so a client that "
            "groups on project_id must read it from here rather than "
            "leaving it to fall back to 'unnamed project'"
        ),
    )
    project_attribution: str = Field(
        ...,
        description=(
            "'explicit' | 'derived_deepest' | 'none' | 'unknown'. 'none' "
            "means probed and matched nothing; 'unknown' means we could "
            "not probe. Only 'unknown' is NEEDS ATTENTION"
        ),
    )
    working_dir: Optional[str] = Field(default=None)
    agent_type: Optional[str] = Field(default=None)
    agent_family: Optional[str] = Field(default=None)
    agent_family_source: Optional[str] = Field(
        default=None,
        description="Unresolved renders as UNKNOWN, never as 'claude'",
    )
    model: Optional[str] = Field(default=None)
    archived_at: Optional[str] = Field(
        default=None,
        description="Visibility only. NEVER hides a running session",
    )
    title: Optional[str] = Field(default=None)
    id: Optional[int] = Field(
        default=None,
        description="sessions.id - what parent_session_id points at",
    )
    parent_session_id: Optional[int] = Field(
        default=None,
        description="sessions.id of the row this one branched from",
    )
    fork_kind: Optional[str] = Field(
        default=None,
        description=(
            "Claude Code's own SessionStart.source. NOT a restart marker "
            "- a restart replacement records 'fork' like any other fork"
        ),
    )
    created_at: Optional[str] = Field(default=None)
    last_seen_running_at: Optional[str] = Field(
        default=None,
        description=(
            "When this session was last PROVEN alive by a tmux probe. "
            "None means never - which is a cannot-determine, not a zero"
        ),
    )
    closed_at: Optional[str] = Field(
        default=None,
        description=(
            "RECENT ROWS ONLY: when this session closed, or the best recorded "
            "proxy when no close was measured (see closed_basis). None on "
            "every other list"
        ),
    )
    closed_basis: Optional[str] = Field(
        default=None,
        description=(
            "What closed_at is: 'closed' (the stop was recorded), "
            "'last_active' (imported row; last recorded work or liveness) or "
            "'added' (nothing else recorded; when the row was added)"
        ),
    )
    last_work_at: Optional[str] = Field(
        default=None,
        description=(
            "When WORK last happened in this session - stamped only from "
            "a Claude Code hook event that means the conversation did "
            "something (claude_hooks.WORK_EVENTS). NOT an opened time: "
            "attaching, selecting or deep-linking to a session never "
            "moves it. NOT last_seen_running_at, which is a liveness "
            "probe that advances on a session nobody has touched. None "
            "means no work has been recorded - a third outcome, sorted "
            "below every value and labelled, never treated as the epoch"
        ),
    )
    pinned_theme: Optional[str] = Field(
        default=None,
        description=(
            "ASLEEP ROWS ONLY: the theme the session wears, its pin else its "
            "project default (the same answer a live row's pinned_theme holds), "
            "so a sleeping session paints its own theme. None on every other "
            "list and when neither rung holds one; the client then paints the "
            "global theme"
        ),
    )
    swarm_agent_id: Optional[int] = Field(default=None)
    swarm_rank: Optional[str] = Field(default=None)
    swarm_character_seed: Optional[int] = Field(default=None)
    swarm_color_slot: Optional[int] = Field(default=None)
    next_wake_at: Optional[float] = Field(
        default=None,
        description=(
            "ASLEEP ROWS ONLY: the soonest epoch second at which something scheduled will wake this sleeping "
            "session (a Task Manager item's fire_at or repeat whose tell lands on it, or an automation aimed at it "
            "with if_asleep wake), stamped by src.api.asleep_wake_listing. None means nothing scheduled will wake "
            "it, or it is not measured, and is never 0; the row draws its wake clock only for a positive number"
        ),
    )
    automations_state: Optional[str] = Field(
        default=None, description="ASLEEP ROWS ONLY: none | ok | warning | error | disabled, or null when not measured.")
    automations_total: Optional[int] = Field(
        default=None, description="ASLEEP ROWS ONLY: scheduled things that will wake this session; null when not measured.")
    automations_enabled: Optional[int] = Field(
        default=None, description="ASLEEP ROWS ONLY: those switched on; null when not measured.")
    automations_next: Optional[List[ScheduledMark]] = Field(
        default=None, description="ASLEEP ROWS ONLY: the scheduled things counted, soonest first, capped; null when not measured.")
    host_key: Optional[str] = Field(
        default=None,
        description="The computer that owns this row: 'local' or null for this one, a paired computer's host key for its shadow row (its asleep agents, #2591)",
    )
    host_label: Optional[str] = Field(default=None, description="That computer's name for the host marker; null for this computer")
    notifications_muted: bool = Field(
        default=False,
        description=(
            "True when this row records that its notifications are muted. "
            "False on a database that predates schema v26, where the "
            "column does not exist and nothing can have been muted"
        ),
    )
    notification_policy_generation: int = Field(
        default=0,
        description=(
            "How many times this row's notification policy has changed. "
            "Steps on mute AND unmute; a queued alert stamped with an "
            "older value is refused rather than delivered late"
        ),
    )
    asleep: bool = Field(
        default=False,
        description=(
            "True when this session was put to sleep (issue #537): "
            "lifecycle 'stopped' with lifecycle_source 'slept_by_user', or "
            "'slept_by_timer' when auto-sleep did it (issue #715), not "
            "deleted. Its tmux session is closed on purpose and it "
            "wakes resumed through POST /sessions/{session_uuid}/wake. An "
            "asleep row belongs in the running lists, never in RECENT"
        ),
    )
    closed: bool = Field(
        default=False,
        description=(
            "True when this session was CLOSED (#1845): stopped (the user closed it, or tmux lost it), not asleep, "
            "not archived, and a real process once (it has a tmux creation epoch). The drawer lists it with its own "
            "closed look; restart reopens it and DELETE /sessions/records/{session_uuid} archives it. Computed by "
            "src.core.session_sleep.is_closed"
        ),
    )
    unread: Optional[bool] = Field(
        default=None,
        description=(
            "ASLEEP ROWS ONLY (issue #749): True when the session carries "
            "the user's manual follow-up flag, which survives the sleep and "
            "the wake; the client paints the moon in the unread colour. "
            "None on every other row, whose unread flag is measured by the "
            "live listing (GET /sessions/list), and None where the store "
            "was not consulted"
        ),
    )


class SessionImportStatus(BaseModel):
    """Whether the one-way first-run session import has run, and if not why.

    THREE OUTCOMES. ``state`` is ``completed`` (the latch is stamped),
    ``pending`` (it has not run and MUST retry - typically because the
    tmux probe could not answer), or ``unavailable`` (the datastore
    itself could not be read, so we cannot even say which of the first
    two applies). ``pending`` is never reported as ``completed``, because
    a stamped latch over a failed probe is permanent silent data loss.
    """

    state: str = Field(
        ..., description="'completed' | 'pending' | 'unavailable'"
    )
    imported_at: Optional[str] = Field(
        default=None,
        description="meta.imported_from_json_at. None whenever not completed",
    )
    pending_reason: Optional[str] = Field(
        default=None,
        description="The tmux probe's own reason token, e.g. 'timeout'",
    )
    notice: Optional[str] = Field(
        default=None,
        description=(
            "Sentence for the home screen. Present ONLY when there is "
            "something to act on, so its presence means act"
        ),
    )
    session_count: Optional[int] = Field(
        default=None,
        description="Rows in the sessions table. None when unavailable",
    )


class RecentSessionsResponse(BaseModel):
    """``GET /sessions/recent`` (S9) - the RECENT group, datastore-backed.

    RECENT is every stored row with ``lifecycle='stopped'`` and
    ``archived_at IS NULL`` - no timer, no retention window. Unlike
    every other launcher surface, this one reads the ``sessions`` table
    rather than a live tmux probe.

    THREE OUTCOMES, carried in ``state``, not folded into ``sessions``:
      'ok'                - ``sessions`` reflects the stored rows as of
        this read.
      'probe_unavailable' - the most recent tmux listing probe failed.
        The stored rows are NOT read as stale-but-still-true here:
        RESTART safety depends on trusting that a 'stopped' row really
        is stopped right now, and a currently-broken probe means that
        cannot be confirmed. ``sessions`` is always ``[]``.
      'never_probed'      - no tmux listing probe has run yet this
        process's lifetime, so probe health is itself an unmeasured
        fact. ``sessions`` is always ``[]``, for the same reason as
        'probe_unavailable'.

    Every row in ``sessions`` (state 'ok') carries ``lifecycle='stopped'``
    by construction of the query; a client must still gate any RESTART
    control on that field itself rather than trusting group membership -
    see ``client/js/launchpad.js``'s RECENT renderer.
    """

    state: str = Field(
        ..., description="'ok' | 'probe_unavailable' | 'never_probed'"
    )
    sessions: List[SessionRecord] = Field(default_factory=list)
    notice: Optional[str] = Field(
        default=None,
        description=(
            "Sentence for the home screen, present whenever state != 'ok'"
        ),
    )
