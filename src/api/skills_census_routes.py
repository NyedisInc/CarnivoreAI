
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.api.skills_manager_routes import _inventory_now, _validate
from src.core.skill_fires.tally import default_store
from src.core.skill_manager.census import WINDOWS, build_census, cutoffs_for

router = APIRouter(tags=["skills"])


@router.get("/skills/census", dependencies=[Depends(require_auth)])
async def get_skills_census(
    request: Request, project_path: Optional[str] = None, profile: Optional[str] = None
) -> Dict[str, Any]:
    """Every skill in every root of one context with its fires in 7, 30 and 90 days.

    Inputs: project_path - a known project; profile - a known Claude profile.
    Output: {state: measured|not_measured, tokens_label, windows, context, skills[]};
      a skill's ``fires`` is null (never 0) when nothing was ever scanned.
    Raises: HTTPException 404 unknown project or profile.
    """
    profiles, resolved = await asyncio.to_thread(_validate, request, profile, project_path)
    snapshot = await request.app.state.services.catalog.index_cache.get()
    inventory = await asyncio.to_thread(_inventory_now, request, profiles, profile, resolved, snapshot)
    cuts = cutoffs_for(datetime.now(timezone.utc), WINDOWS)
    fires = await asyncio.to_thread(default_store().usage_by_skill, cuts)
    return build_census(inventory, fires)
