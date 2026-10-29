
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.api import skill_card_art_bulk
from src.api.auth import require_auth
from src.api.skills_manager_routes import resolve_location
from src.core import terminal_background
from src.core.companies import hero_images
from src.core.skill_manager import card_art
from src.api.error_response import api_error

router = APIRouter(tags=["skills"])

_IMMUTABLE = "private, max-age=31536000, immutable"
_REVALIDATE = "no-cache, must-revalidate"


@router.get("/skills/card-art/{art_id}", dependencies=[Depends(require_auth)])
def get_card_art(art_id: str, rev: Optional[str] = None) -> FileResponse:
    """Serve one skill's stored card image. Inputs: art_id (from ``card_art.id`` in ``GET /skills``), rev.

    Raises: HTTPException 404 when none (an id that is not 32 hex chars finds nothing).
    """
    path = card_art.find(art_id)
    media_type = terminal_background.content_type_for_extension(path.suffix.lstrip(".")) if path else None
    if path is None or media_type is None:
        raise HTTPException(status_code=404, detail="no stored image")
    cache = _IMMUTABLE if rev is not None and rev == hero_images.rev_of(path) else _REVALIDATE
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": cache})


class RegenerateRequest(BaseModel):
    """Body of the regenerate route: the context the location id was listed in. No field is a path."""

    project_path: Optional[str] = None
    profile: Optional[str] = None


@router.post("/skills/locations/{location_id}/card-art/regenerate", status_code=202, dependencies=[Depends(require_auth)])
async def regenerate_card_art(request: Request, location_id: str, body: RegenerateRequest) -> dict:
    """Queue a new card image for one listed skill location. Output: {"queued": bool} (false = already queued).

    Raises: HTTPException 404 unknown project, profile or location; 409 when the AI feature has no target.
    """
    hit, _root = await resolve_location(request, location_id, body.project_path, body.profile)
    if not card_art.enabled():
        raise HTTPException(status_code=409, detail="choose an image model for skill card images in Settings, AI")
    key = card_art.art_id(hit["harness"], hit["name"], hit["location_id"])
    return {"queued": card_art.schedule(key, hit["name"], hit.get("description") or "", regenerate=True)}


@router.post("/skills/card-art-bulk", status_code=202, dependencies=[Depends(require_auth)])
async def regenerate_all_card_art(request: Request) -> dict:
    """Regenerate every local skill's card image (global context, shadowed ones skipped, at most 300) as one background job.

    Output: the job status {"state", "total", "done", "generated", "failed", "skipped"}.
    Raises: HTTPException 409 when the AI feature has no target or a job is already running.
    """
    if not card_art.enabled():
        raise HTTPException(status_code=409, detail="choose an image model for skill card images in Settings, AI")
    try:
        return await skill_card_art_bulk.start(request.app)
    except RuntimeError as exc:
        raise api_error(409, "conflict", exc, step="regenerate_all_card_art") from exc


@router.get("/skills/card-art-bulk", dependencies=[Depends(require_auth)])
def card_art_bulk_status() -> dict:
    """The bulk job's state. Output: {"state": "idle"|"running"|"done"|"error", "total", "done", "generated", "failed", "skipped"}."""
    return skill_card_art_bulk.status()
