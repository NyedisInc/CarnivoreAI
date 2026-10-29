
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from src.api.auth import require_auth
from src.core.skills.bundled_install import BundledSkillError
from src.core.skills.required import REQUIRED_SKILLS, clear_declined, ensure_required, install_one, required_states

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])


async def run_required_pass(app: FastAPI) -> None:
    await ensure_required(app.state.services)


@router.get("/catalog/required-skills", dependencies=[Depends(require_auth)])
async def get_required_skills(request: Request) -> Dict[str, Any]:
    """Each required first-party skill's standing. Output: {items: [{item_id, required, state, install_id, local_edits}]}."""
    states = await asyncio.to_thread(required_states, request.app.state.services)
    required = {s.item_id: s.required for s in REQUIRED_SKILLS}
    return {"items": [{"item_id": s.item_id, "required": required[s.item_id], "state": s.state,
                       "install_id": s.install_id, "local_edits": s.local_edits} for s in states]}


@router.post("/catalog/required-skills/{publisher}/{name}/install", dependencies=[Depends(require_auth)])
async def install_required_skill(request: Request, publisher: str, name: str) -> Dict[str, Any]:
    """The offer: reinstall a required skill the person removed, from the bundled copy.

    Raises: HTTPException(404) not a required skill; 409 ``blocked`` when a folder of that name that is not carnivore's is
    in the way, or no agent is present.
    """
    item_id = f"{publisher}/{name}"
    if item_id not in {s.item_id for s in REQUIRED_SKILLS}:
        raise HTTPException(status_code=404, detail=f"{item_id!r} is not a required skill")
    services = request.app.state.services

    def _install() -> None:
        with closing(services.catalog.open_db()) as conn:
            clear_declined(conn, item_id)
        install_one(services, item_id)

    try:
        await asyncio.to_thread(_install)
    except BundledSkillError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "detail": str(exc)}) from exc
    return {"item_id": item_id, "ok": True}
