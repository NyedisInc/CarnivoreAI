
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

START_GRANTS = ("sessions.read", "sessions.create")
STATUS_REFUSED = "refused"
STATUS_NOT_ATTEMPTED = "not_attempted"
CODE_GRANT_NEEDED = "grant_needed"


def _answer(status: str, session_uuid: Optional[str], detail: str, code: str = "", **extra: Any) -> Dict[str, Any]:
    return {"status": status, "code": code, "session_uuid": session_uuid, "session_name": extra.get("session_name"),
            "session_id": extra.get("session_id"), "detail": detail}


async def start_after_restore(ctx: CplugContext, session_uuid: Optional[str], wrapper: Optional[str]) -> Dict[str, Any]:
    if not session_uuid or not wrapper:
        return _answer(STATUS_NOT_ATTEMPTED, session_uuid, "the transcript is restored. no session row or wrapper is "
                       "recorded for this point, so nothing was started")
    sessions = getattr(ctx, "sessions", None)
    resume = getattr(sessions, "resume", None) if sessions is not None else None
    if resume is None:
        return _answer(STATUS_REFUSED, session_uuid, "the transcript is restored. starting its session needs the "
                       f"{' and '.join(START_GRANTS)} permissions; grant them to restore points on the plugins page",
                       code=CODE_GRANT_NEEDED)
    try:
        started = await resume(session_uuid, wrapper)
    except HTTPException as exc:
        return _answer(STATUS_REFUSED, session_uuid, str(exc.detail))
    logger.info("save_restore_session_started", session_uuid=session_uuid, status=started.get("status"))
    return _answer(started.get("status") or STATUS_REFUSED, started.get("session_uuid") or session_uuid,
                   started.get("detail") or "", session_name=started.get("session_name"),
                   session_id=started.get("session_id"))
