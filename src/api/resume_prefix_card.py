
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi.responses import JSONResponse

from src.core.launch_profiles.agent_resume import ResumePrefixNotApproved
from src.core.mcp import pending

logger = structlog.get_logger()

ACTION = "approve_resume_prefix"


def raise_card(prefix: str, tmux_name: str) -> Optional[str]:
    async def execute() -> dict:
        from src.api import launch_profiles_routes  # noqa: PLC0415

        block = await launch_profiles_routes.approve_resume_prefix(launch_profiles_routes.ResumePrefixBody(prefix=prefix))
        text = f"{prefix} may now resume sessions on this computer; restart {tmux_name} again to resume it"
        return {"content": [{"type": "text", "text": text}], "approved_resume_prefixes": block["approved_resume_prefixes"]}

    plain = (f"let {prefix} resume sessions on this computer. approve and restart {tmux_name} again to resume it; "
             f"deny and {tmux_name} is not resumed")
    try:
        item = pending.get_store().create(
            caller_session_id="", caller_tmux=tmux_name, target_session_id="", target_tmux=tmux_name,
            action=ACTION, args_summary=f"approve resume command prefix {prefix} on this computer", execute=execute,
            args={"prefix": prefix}, beast_eligible=False, extra={"plain": plain, "target_name": tmux_name})
    except pending.PendingLimitError as exc:
        logger.warning("resume_prefix_card_not_raised", prefix=prefix, name=tmux_name, error=str(exc))
        return None
    logger.info("resume_prefix_card_raised", id=item.id, prefix=prefix, name=tmux_name)
    return item.id


async def refused(_request: Any, exc: ResumePrefixNotApproved) -> JSONResponse:
    approval_id = raise_card(exc.prefix, exc.tmux_name) if exc.ask else None
    detail = (f"not resumed: {exc.prefix} is not approved to resume sessions on this computer. "
              + ("approve the card in approvals, then restart again" if approval_id else
                 "approve it in approvals, or with POST /api/v1/launch-profiles/resume-prefixes"))
    return JSONResponse(status_code=409, content={
        "code": "resume_prefix_not_approved", "prefix": exc.prefix, "detail": detail,
        "approve": "POST /api/v1/launch-profiles/resume-prefixes", "approval_id": approval_id})
