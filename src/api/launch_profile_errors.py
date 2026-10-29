
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import HTTPException

from src.core.launch_profiles import create_seam, restart_seam
from src.core.launch_profiles.resolve import LaunchProfileNotFound

logger = structlog.get_logger()


def refuse_gone_profile(settings: Any, agent_type: Optional[str], raw_record: Optional[str]) -> None:
    try:
        restart_seam.check_relaunch(settings, agent_type, raw_record)
    except LaunchProfileNotFound as exc:
        logger.warning("relaunch_launch_profile_missing", profile=exc.profile_id)
        raise HTTPException(status_code=400, detail={
            "code": exc.codes[0], "codes": list(exc.codes), "detail": str(exc),
            "wrapper_options": create_seam.known_pick_ids(settings),
        })


def unknown_profile_codes(settings: Any, agent_type: Optional[str], verdict: str) -> dict:
    from src.core.session_agent_choice import CHOICE_UNKNOWN

    if verdict != CHOICE_UNKNOWN:
        return {}
    try:
        create_seam.check_explicit_pick(settings, agent_type)
    except LaunchProfileNotFound as exc:
        return {"code": exc.codes[0], "codes": list(exc.codes)}
    return {}
