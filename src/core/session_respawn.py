
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
    if command_uuid:
        return CONVERSATION_RESUMED
    if resume_outcome in (CONVERSATION_NONE_RECORDED, CONVERSATION_RESUMED):
        return CONVERSATION_NONE_RECORDED
    return CONVERSATION_UNKNOWN


def _with_continuity(base: str, conversation: str) -> str:
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
    if not command:
        return None
    found = _RESUME_RE.search(command)
    return found.group(1) if found else None


def refuse_if_transcript_missing(
    plan: RespawnPlan, presence_outcome: Optional[str], detail: str = ""
) -> RespawnPlan:
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

PANE_UNKNOWN: str = "unknown"

ALL_PANE_STATES: frozenset[str] = frozenset({PANE_DEAD, PANE_ALIVE, PANE_UNKNOWN})


def pane_state_from_probe(probe_ok: bool, pane_dead: Optional[str]) -> str:
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

    kind: str
    ok: bool
    detail: str = ""
    command: Optional[str] = None
    chosen: bool = False
    killed_live_pane: bool = False
    epoch_before: Optional[int] = None
    epoch_after: Optional[int] = None
    conversation: str = CONVERSATION_UNKNOWN
