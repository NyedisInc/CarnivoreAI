
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.api.project_move_routes import move_project_for
from src.api.projects_routes import (
    archive_project_for,
    delete_project_for,
    unarchive_project_for,
    update_project_for,
)
from src.models import (
    ProjectMoveRequest,
    ProjectMoveResponse,
    ProjectResponse,
    SuccessResponse,
    UpdateProjectRequest,
)

router = APIRouter(dependencies=[Depends(require_auth)])


@router.delete("/projects/by-id/{project_id:int}", response_model=SuccessResponse)
async def delete_project_by_id(project_id: int, request: Request) -> SuccessResponse:
    """Delete a project for good, addressed by row id. Same body and errors as ``DELETE /projects/{name}``."""
    return await delete_project_for(project_id, request)


@router.patch("/projects/by-id/{project_id:int}", response_model=ProjectResponse)
async def update_project_by_id(project_id: int, body: UpdateProjectRequest) -> ProjectResponse:
    """Update a project's name, descriptions, launch profile or color, addressed by row id."""
    return await update_project_for(project_id, body)


@router.post("/projects/by-id/{project_id:int}/archive", response_model=ProjectResponse)
async def archive_project_by_id(project_id: int) -> ProjectResponse:
    """Archive a project (and its non-live sessions), addressed by row id."""
    return await archive_project_for(project_id)


@router.post("/projects/by-id/{project_id:int}/unarchive", response_model=ProjectResponse)
async def unarchive_project_by_id(project_id: int) -> ProjectResponse:
    """Restore an archived project, addressed by row id."""
    return await unarchive_project_for(project_id)


@router.post("/projects/by-id/{project_id:int}/move", response_model=ProjectMoveResponse)
async def move_project_by_id(project_id: int, body: ProjectMoveRequest, request: Request) -> ProjectMoveResponse:
    """Plan or run a move of a project's folder, addressed by row id."""
    return await move_project_for(project_id, body, request)
