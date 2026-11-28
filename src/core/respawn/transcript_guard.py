
from __future__ import annotations

from typing import Optional

from src.core.session_respawn import RESPAWN_OFFLOADED, RESPAWN_TRANSCRIPT_MISSING, RespawnPlan
from src.core.session_resume_target import CONVERSATION_UNKNOWN


def refuse_if_transcript_missing(
    plan: RespawnPlan, presence_outcome: Optional[str], detail: str = ""
) -> RespawnPlan:
    if presence_outcome != "absent" or not plan.resume_uuid:
        return plan
    from src.core.backup_health import offload_guard

    off = offload_guard.lookup(plan.resume_uuid)
    if off is not None:
        return RespawnPlan(kind=RESPAWN_OFFLOADED, command=None, conversation=CONVERSATION_UNKNOWN, detail=off.detail, resume_uuid=plan.resume_uuid)
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
