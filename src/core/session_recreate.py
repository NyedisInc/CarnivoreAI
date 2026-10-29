
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import structlog

from src.core.session_imported_restart import (
    ImportedRestartPlan,
    ResumeDirectory,
    plan_imported_restart,
)
from src.core.session_recreate_presence import (
    TMUX_GONE,
    TMUX_PRESENT,
    TMUX_UNKNOWN,
    TmuxPresence,
)
from src.core.session_respawn import (
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_NOT_DEAD,
    RespawnPlan,
)
from src.core.session_resume_target import (
    CONVERSATION_NONE_RECORDED,
    CONVERSATION_RESUMED,
    CONVERSATION_UNKNOWN,
)

logger = structlog.get_logger()

RECREATE: str = "recreate"


def has_tmux_identity(row: Optional[Mapping[str, Any]]) -> bool:
    from src.core.session_imported_restart import is_imported_row

    if row is None:
        return False
    return not is_imported_row(row)


@dataclass(frozen=True)
class RecreatePlan:

    kind: str
    command: Optional[str] = None
    conversation: str = CONVERSATION_UNKNOWN
    presence: str = TMUX_UNKNOWN
    working_dir: Optional[str] = None
    tmux_name: Optional[str] = None
    reuse_session_id: Optional[int] = None
    label: Optional[str] = None
    agent_type: Optional[str] = None
    detail: str = ""

    @property
    def actionable(self) -> bool:
        return self.kind == RECREATE and bool(self.command)


def plan_recreate(
    row: Optional[Mapping[str, Any]],
    *,
    row_read_ok: bool,
    presence: TmuxPresence,
    choice_verdict: Optional[str] = None,
    choice_command: Optional[str] = None,
    choice_detail: str = "",
    agent_type: Optional[str] = None,
    directory: Optional[ResumeDirectory] = None,
) -> RecreatePlan:
    if not row_read_ok or row is None:
        return RecreatePlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            presence=presence.outcome,
            detail=(
                "the session's row could not be read, so what recreating "
                "it would do was not evaluated"
            ),
        )

    tmux_name = _str(row.get("tmux_name"))

    if presence.outcome == TMUX_PRESENT:
        return RecreatePlan(
            kind=RESPAWN_NOT_DEAD,
            presence=presence.outcome,
            tmux_name=tmux_name,
            reuse_session_id=_row_id(row),
            detail=presence.detail,
        )

    if presence.outcome != TMUX_GONE:
        return RecreatePlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            presence=presence.outcome,
            tmux_name=tmux_name,
            reuse_session_id=_row_id(row),
            detail=presence.detail
            or (
                "whether this session's tmux is still running could not "
                "be determined, so nothing was offered"
            ),
        )

    inner: ImportedRestartPlan = plan_imported_restart(
        row,
        row_read_ok=True,
        choice_verdict=choice_verdict,
        choice_command=choice_command,
        choice_detail=choice_detail,
        agent_type=agent_type,
        directory=directory,
    )

    if inner.kind != RESPAWN_AGENT:
        return RecreatePlan(
            kind=inner.kind,
            command=inner.command,
            conversation=inner.conversation,
            presence=presence.outcome,
            working_dir=inner.working_dir,
            tmux_name=tmux_name,
            reuse_session_id=inner.reuse_session_id or _row_id(row),
            label=inner.label,
            agent_type=agent_type,
            detail=inner.detail,
        )

    return RecreatePlan(
        kind=RECREATE,
        command=inner.command,
        conversation=inner.conversation,
        presence=presence.outcome,
        working_dir=inner.working_dir,
        tmux_name=tmux_name,
        reuse_session_id=inner.reuse_session_id,
        label=inner.label,
        agent_type=agent_type,
        detail=_recreate_sentence(inner.conversation, inner.working_dir),
    )


def _recreate_sentence(conversation: str, working_dir: Optional[str]) -> str:
    where = f" in {working_dir!r}" if working_dir else ""
    if conversation == CONVERSATION_RESUMED:
        tail = "on the same conversation"
    elif conversation == CONVERSATION_NONE_RECORDED:
        tail = (
            "WITHOUT its history, because no conversation is recorded on "
            "this row"
        )
    else:
        tail = (
            "and nothing claims to resume its history, because the "
            "conversation could not be determined"
        )
    return (
        f"this session's tmux is gone, so recreating it starts a new one"
        f"{where} on the same record, {tail}. its old scrollback does not "
        "come back."
    )


def as_respawn_plan(plan: RecreatePlan) -> RespawnPlan:
    return RespawnPlan(
        kind=plan.kind,
        command=plan.command,
        detail=plan.detail,
        chosen=bool(plan.agent_type),
        conversation=plan.conversation,
        kills_live_pane=False,
    )


def _row_id(row: Mapping[str, Any]) -> Optional[int]:
    value = row.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
