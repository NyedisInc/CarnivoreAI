
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

from src.core.session_resume_target import (
    CONVERSATION_NONE_RECORDED,
    CONVERSATION_RESUMED,
    CONVERSATION_UNKNOWN,
    continuity_from_command,
    continuity_phrase,
)

RESPAWN_AGENT: str = "agent"

RESPAWN_REPLAY: str = "replay"

RESPAWN_SHELL: str = "shell"

RESPAWN_NOT_DEAD: str = "not_dead"

# could not
RESPAWN_CANNOT_DETERMINE: str = "cannot_determine"

RESPAWN_TRANSCRIPT_MISSING: str = "transcript_missing"

ALL_RESPAWN_KINDS: frozenset[str] = frozenset(
    {
        RESPAWN_AGENT,
        RESPAWN_REPLAY,
        RESPAWN_SHELL,
        RESPAWN_NOT_DEAD,
        RESPAWN_CANNOT_DETERMINE,
        RESPAWN_TRANSCRIPT_MISSING,
    }
)

ACTIONABLE_RESPAWN_KINDS: frozenset[str] = frozenset(
    {RESPAWN_AGENT, RESPAWN_REPLAY, RESPAWN_SHELL}
)

LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION: str = "mcp_bridge_migration"
LIVE_RESTART_REASON_USAGE_LIMIT_ROTATION: str = "usage_limit_rotation"
LIVE_RESTART_REASONS: frozenset[str] = frozenset({
    LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION,
    LIVE_RESTART_REASON_USAGE_LIMIT_ROTATION,
})


@dataclass(frozen=True)
class RespawnPlan:

    kind: str
    command: Optional[str] = None
    detail: str = ""
    chosen: bool = False
    resume_uuid: Optional[str] = None
    conversation: str = CONVERSATION_UNKNOWN
    kills_live_pane: bool = False
    kill_reason: Optional[str] = None

    @property
    def actionable(self) -> bool:
        return self.kind in ACTIONABLE_RESPAWN_KINDS


def resolve_respawn_plan(
    *,
    probe_ok: bool,
    pane_dead: Optional[str],
    pane_start_command: Optional[str],
    agent_command: Optional[str],
    chosen_agent_command: Optional[str] = None,
    chosen_agent_type: Optional[str] = None,
    resume_outcome: Optional[str] = None,
    live_restart_confirmed: bool = False,
    live_restart_reason: Optional[str] = None,
) -> RespawnPlan:
    if live_restart_reason is not None and live_restart_reason not in LIVE_RESTART_REASONS:
        return RespawnPlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            detail=f"refused: {live_restart_reason!r} is not a named restart reason",
        )
    if not probe_ok or pane_dead is None:
        return RespawnPlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            detail=(
                "tmux did not answer when asked about this pane, so what "
                "it was running cannot be determined"
            ),
        )

    alive = pane_dead.strip() != "1"
    if alive and not live_restart_confirmed:
        return RespawnPlan(
            kind=RESPAWN_NOT_DEAD,
            detail="this session is still running; there is nothing to restart",
        )

    plan = _rung_from_start_command(
        pane_start_command=pane_start_command,
        agent_command=agent_command,
        chosen_agent_command=chosen_agent_command,
        chosen_agent_type=chosen_agent_type,
        resume_outcome=resume_outcome,
    )
    if not alive:
        return plan
    return replace(plan, kills_live_pane=plan.actionable,
                   kill_reason=live_restart_reason if plan.actionable else None)


def _conversation_for(
    command_uuid: Optional[str], resume_outcome: Optional[str]
) -> str:
    """What happens to the conversation, given the command and the lookup.

    Description: THE COMMAND WINS. If the string that is about to run
        carries a ``--resume <uuid>``, the conversation IS resumed, and no
        caller's belief can contradict the argv. Only when there is no
        uuid on the command does the caller's own lookup of
        ``sessions.claude_session_uuid`` decide between "the row records
        none" and "the row could not be read".

        An unrecognised or missing lookup answers
        :data:`CONVERSATION_UNKNOWN`, never
        :data:`CONVERSATION_NONE_RECORDED`: "nobody told me" is not
        "nothing is there".

    Inputs:
        command_uuid: the uuid found on the command that will run, or
            None.
        resume_outcome: one of the ``CONVERSATION_*`` constants, or None.

    Output:
        str: one of the ``CONVERSATION_*`` constants.

    Example:
        >>> _conversation_for('abc', None)
        'resumed'
        >>> _conversation_for(None, CONVERSATION_NONE_RECORDED)
        'none_recorded'
        >>> _conversation_for(None, None)
        'unknown'
    """
    if command_uuid:
        return CONVERSATION_RESUMED
    if resume_outcome in (CONVERSATION_NONE_RECORDED, CONVERSATION_RESUMED):
        # nothing to resume
        return CONVERSATION_NONE_RECORDED
    return CONVERSATION_UNKNOWN


def _with_continuity(base: str, conversation: str) -> str:
    """Append the conversation clause to a rung's sentence.

    Description: the rung sentence and the continuity clause are joined
        in ONE place so every rung says the same thing about the same
        outcome. The wording of the clause itself lives in
        ``session_resume_target.continuity_phrase`` - this only decides
        the punctuation, because "and it resumes" reads as a
        continuation while the other two read as a caveat.

    Inputs:
        base: the rung's own sentence, no trailing punctuation.
        conversation: one of the ``CONVERSATION_*`` constants.

    Example:
        >>> _with_continuity('restarting it', CONVERSATION_RESUMED)
        'restarting it, resuming the same conversation'
    """
    joiner = ", " if conversation == CONVERSATION_RESUMED else "; "
    return f"{base}{joiner}{continuity_phrase(conversation)}"


def _rung_from_start_command(
    *,
    pane_start_command: Optional[str],
    agent_command: Optional[str],
    chosen_agent_command: Optional[str],
    chosen_agent_type: Optional[str],
    resume_outcome: Optional[str] = None,
) -> RespawnPlan:
    """Classify a pane by its start command alone, liveness NOT considered.

    Description: the shared tail of the ladder - the explicit-choice
        branch plus the three rungs. Both entry points end here, which is
        what makes the preview structurally incapable of drifting from
        the action: :func:`resolve_respawn_plan` reaches it through the
        probe gate AND the liveness gate, and
        :func:`project_restart_rung` reaches it through the probe gate
        only. Those four lines are the entire difference between them.

        Private on purpose. Calling it directly skips BOTH gates, which
        would classify a pane nobody has established is readable or dead.

    Inputs:
        pane_start_command: raw ``#{pane_start_command}``. Empty string
            means tmux positively recorded none; None means the field was
            not returned at all.
        agent_command: what the app's stored ``agent_type`` resolves to
            now, or None when it has no record.
        chosen_agent_command: command for a wrapper the user picked in
            this request, or None.
        chosen_agent_type: that wrapper's id, used only to name it in the
            sentence shown to the user.
        resume_outcome: the caller's conversation lookup, used for the
            SENTENCE and the ``conversation`` field only. It selects no
            rung, so the ladder is the same ladder it was.

    Output:
        RespawnPlan: one of AGENT / REPLAY / SHELL / CANNOT_DETERMINE.
            Never NOT_DEAD - liveness is not visible from here.

    Example:
        >>> _rung_from_start_command(pane_start_command='',
        ...     agent_command=None, chosen_agent_command=None,
        ...     chosen_agent_type=None).kind
        'shell'
    """
    picked = (chosen_agent_command or "").strip()
    if picked:
        named = (chosen_agent_type or "").strip() or "the agent"
        if pane_start_command is None:
            why = (
                f"tmux did not report a start command for this pane, but "
                f"{named} is what you picked and is what will be started"
            )
        elif not pane_start_command.strip():
            why = (
                f"this pane was opened as a plain shell; {named} is what "
                f"you picked and will be started in it instead"
            )
        else:
            why = (
                f"starting {named}, which you picked, instead of what this "
                f"session was launched with"
            )
        picked_uuid = resume_uuid_in(picked)
        picked_conversation = _conversation_for(picked_uuid, resume_outcome)
        return RespawnPlan(
            kind=RESPAWN_AGENT,
            command=picked,
            detail=_with_continuity(why, picked_conversation),
            chosen=True,
            resume_uuid=picked_uuid,
            conversation=picked_conversation,
        )

    if pane_start_command is None:
        return RespawnPlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            detail=(
                "tmux did not report a start command for this pane, so "
                "what to restart cannot be determined"
            ),
        )

    started = pane_start_command.strip()
    if not started:
        return RespawnPlan(
            kind=RESPAWN_SHELL,
            command=None,
            detail=_with_continuity(
                "this pane was opened as a plain shell; restarting opens "
                "one again",
                CONVERSATION_NONE_RECORDED,
            ),
            conversation=CONVERSATION_NONE_RECORDED,
        )

    resolved_agent = (agent_command or "").strip()
    if resolved_agent:
        agent_uuid = resume_uuid_in(resolved_agent)
        agent_conversation = _conversation_for(agent_uuid, resume_outcome)
        return RespawnPlan(
            kind=RESPAWN_AGENT,
            command=resolved_agent,
            detail=_with_continuity(
                "restarting the agent this session was launched with",
                agent_conversation,
            ),
            resume_uuid=agent_uuid,
            conversation=agent_conversation,
        )

    replay_conversation = continuity_from_command(pane_start_command)
    return RespawnPlan(
        kind=RESPAWN_REPLAY,
        command=None,
        resume_uuid=resume_uuid_in(pane_start_command),
        conversation=replay_conversation,
        detail=_with_continuity(
            "restarting the command tmux recorded for this pane",
            replay_conversation,
        ),
    )


def project_restart_rung(
    *,
    probe_ok: bool,
    pane_start_command: Optional[str],
    agent_command: Optional[str],
    chosen_agent_command: Optional[str] = None,
    chosen_agent_type: Optional[str] = None,
    resume_outcome: Optional[str] = None,
) -> RespawnPlan:
    """Which rung a restart WOULD land on, ignoring whether the pane is alive.

    Inputs:
        probe_ok: True iff the tmux pane query actually answered. False
            means the start command carries no information and the rung
            is ``cannot_determine``.
        pane_start_command: raw ``#{pane_start_command}``.
        agent_command: what the stored ``agent_type`` resolves to, or None.
        chosen_agent_command: command for a wrapper picked in this
            request, or None for the baseline projection.
        chosen_agent_type: that wrapper's id, for the sentence only.
        resume_outcome: the caller's conversation lookup, exactly as
            :func:`resolve_respawn_plan` takes it. IT IS NOT A LIVENESS
            INPUT and cannot become one: it distinguishes
            ``'none_recorded'`` from ``'unknown'`` in a SENTENCE and
            touches no rung, so this function stays structurally
            incapable of setting ``kills_live_pane``.

    Output:
        RespawnPlan: AGENT / REPLAY / SHELL / CANNOT_DETERMINE. Never
            NOT_DEAD, because liveness is not what this answers, and
            ``kills_live_pane`` is ALWAYS False for the same reason -
            this function is never told whether the pane is alive, so it
            structurally cannot hand out the permission to kill one. That
            is what stops a UI wiring a projected rung to a button from
            turning a prediction into a kill.

    Example:
        >>> project_restart_rung(probe_ok=True, pane_start_command='',
        ...     agent_command='keyc').kind
        'shell'
        >>> project_restart_rung(probe_ok=True, pane_start_command='"keyc"',
        ...     agent_command='keyc').kills_live_pane
        False
    """
    if not probe_ok:
        return RespawnPlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            detail=(
                "tmux did not answer when asked about this pane, so what "
                "a restart would run cannot be determined"
            ),
        )
    return _rung_from_start_command(
        pane_start_command=pane_start_command,
        agent_command=agent_command,
        chosen_agent_command=chosen_agent_command,
        chosen_agent_type=chosen_agent_type,
        resume_outcome=resume_outcome,
    )


_RESUME_RE = re.compile(
    r"(?:--resume['\"]?[=\s]+|(?<![\w-])resume\s+)['\"]?"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def resume_uuid_in(command: Optional[str]) -> Optional[str]:
    """The conversation id a command would resume, if any.

        CODEX RESUMES ON A SUBCOMMAND, NOT A FLAG (``codex resume <uuid>``,
        see ``session_restart.resume_arguments``), so this also matches the
        bare ``resume <uuid>`` form. Without that, every codex restart's
        recorded start command read as carrying no resume at all, and the
        transcript-presence check it feeds skipped straight to
        ``none_recorded`` even though the pane was, in fact, resuming.

    Inputs:
        command: a shell command string, or None.

    Output:
        Optional[str]: the uuid, or None when the command resumes
            nothing. ``--continue`` names no uuid and so cannot be
            checked; it is deliberately not matched.
    """
    if not command:
        return None
    found = _RESUME_RE.search(command)
    return found.group(1) if found else None


def refuse_if_transcript_missing(
    plan: RespawnPlan, presence_outcome: Optional[str], detail: str = ""
) -> RespawnPlan:
    """Turn an actionable plan into a refusal when its transcript is gone.

    Description: the pure half of the transcript guard. The caller does
        the filesystem check (``session_transcript_presence``) and hands
        the OUTCOME here, which keeps this module free of I/O exactly as
        the rest of the ladder is.

        ONLY A DEFINITE ABSENCE REFUSES. ``present`` and ``unchecked``
        both pass through untouched, because not having been able to look
        is not evidence that a file is gone - refusing on it would break
        restart on every machine whose corpus lives somewhere the checker
        was not told about. That is the same direction
        ``session_transcript_presence`` documents at length.

    Output:
        RespawnPlan: the SAME plan, or a RESPAWN_TRANSCRIPT_MISSING
            refusal carrying the uuid that could not be found. THE
            REFUSAL NEVER CARRIES ``kills_live_pane``: it is built fresh
            rather than copied, so a confirmed live restart whose
            transcript has gone cannot reach ``-k``. That is the whole
            point of routing the live path through this guard - the
            incident it exists for is a resume against a deleted
            transcript, and on the live path the pane it would kill was
            working.

    Example:
        >>> p = RespawnPlan(kind=RESPAWN_REPLAY, resume_uuid='u')
        >>> refuse_if_transcript_missing(p, 'absent').kind
        'transcript_missing'
    """
    if presence_outcome != "absent" or not plan.resume_uuid:
        return plan
    return RespawnPlan(
        kind=RESPAWN_TRANSCRIPT_MISSING,
        command=None,
        conversation=CONVERSATION_UNKNOWN,
        detail=(
            detail
            or (
                f"the conversation this session would resume "
                f"({plan.resume_uuid}) has no transcript on this machine, "
                f"so restarting it would open a pane that exits at once"
            )
        ),
        resume_uuid=plan.resume_uuid,
    )


PANE_DEAD: str = "dead"

PANE_ALIVE: str = "alive"

# did not answer
PANE_UNKNOWN: str = "unknown"

ALL_PANE_STATES: frozenset[str] = frozenset({PANE_DEAD, PANE_ALIVE, PANE_UNKNOWN})


def pane_state_from_probe(probe_ok: bool, pane_dead: Optional[str]) -> str:
    """Whether the pane is dead, alive, or could not be read.

    Inputs:
        probe_ok: True iff the tmux pane query answered.
        pane_dead: raw ``#{pane_dead}`` ("0" / "1"), or None.

    Output:
        str: PANE_DEAD, PANE_ALIVE or PANE_UNKNOWN.

    Example:
        >>> pane_state_from_probe(True, "0")
        'alive'
        >>> pane_state_from_probe(False, None)
        'unknown'
    """
    if not probe_ok or pane_dead is None:
        return PANE_UNKNOWN
    return PANE_DEAD if pane_dead.strip() == "1" else PANE_ALIVE


RESPAWN_PANE_FORMAT: str = "#{pane_dead}|#{pane_dead_status}|#{pane_start_command}"


def parse_respawn_probe(raw: str) -> tuple[str, str, str]:
    parts = raw.rstrip("\r\n").split("|", 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0].strip(), parts[1].strip(), parts[2]


@dataclass(frozen=True)
class RespawnResult:
    """Outcome of an attempted respawn, as reported to the API and the UI.

    ``kind`` is the ladder's verdict and is ALWAYS meaningful; ``ok`` says
    whether a process is actually running in the pane now. The pair is
    deliberately not collapsed into one field, because "we knew what to run
    and it died again" (kind=agent, ok=False) is a different report from
    "we could not tell what to run" (kind=cannot_determine, ok=False), and
    the user needs to be told which.
    """

    kind: str
    ok: bool
    detail: str = ""
    command: Optional[str] = None
    chosen: bool = False
    killed_live_pane: bool = False
    epoch_before: Optional[int] = None
    epoch_after: Optional[int] = None
    conversation: str = CONVERSATION_UNKNOWN
