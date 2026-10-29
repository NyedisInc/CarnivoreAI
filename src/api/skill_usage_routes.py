
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from src.api.auth import require_auth
from src.core.skill_fires.tally import default_store
from src.models.sessions import SkillUsage

router = APIRouter()

_WINDOWS = (7, 30, 90)


def read_usage(skill: str, now: datetime) -> SkillUsage:
    cutoffs = [(now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S") for d in _WINDOWS]
    counts = default_store().usage(skill, cutoffs)
    if counts is None:
        return SkillUsage(skill=skill, state="not_measured")
    return SkillUsage(skill=skill, state="measured",
                      fired_7d=counts[0], fired_30d=counts[1], fired_90d=counts[2])


@router.get("/skill-fires/usage", response_model=SkillUsage,
            dependencies=[Depends(require_auth)])
async def get_skill_usage(skill: str = Query(..., min_length=1, max_length=128)) -> SkillUsage:
    """Fires of one skill in the last 7, 30 and 90 days on this machine.

    Inputs: skill (str, 1..128). Output: SkillUsage.
    Example: GET /api/v1/skill-fires/usage?skill=deploy
    """
    return await asyncio.to_thread(read_usage, skill, datetime.now(timezone.utc))
