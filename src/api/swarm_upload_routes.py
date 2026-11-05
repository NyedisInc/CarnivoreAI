
from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.api.auth import require_auth
from src.api.session_input_routes import store_upload
from src.api.swarm_routes import NEEDS_ON
from src.core.swarm import views
from src.models import UploadImageResponse

logger = structlog.get_logger()
router = APIRouter(prefix="/swarm", tags=["swarm"], dependencies=[Depends(require_auth)])


@router.post("/agents/{agent_id}/upload-file", response_model=UploadImageResponse, status_code=201, dependencies=NEEDS_ON)
async def upload_agent_file(agent_id: int, file: UploadFile = File(...)) -> UploadImageResponse:
    """Save one file into an agent's folder so the owner's next order can name it.

    Inputs: agent_id; file (multipart). Output: {path: absolute saved path, filename, size} (201).
    Raises: 404 ``agent_not_found`` (unknown or turned off), 409 ``agent_folder_missing`` (its folder is gone),
      400/413/500 as the session upload route.
    """
    try:
        agent = await views.get_agent_row(agent_id)
    except views.AgentMissing:
        agent = None
    if agent is None or agent["torn_down_at"] is not None:
        raise HTTPException(status_code=404, detail={"code": "agent_not_found", "message": "no such agent"})
    folder = agent["repo_dir"]
    if not folder or not os.path.isdir(folder):
        raise HTTPException(status_code=409, detail={"code": "agent_folder_missing", "message": "the agent's folder is gone"})
    saved = await store_upload(file, folder)
    logger.info("swarm_agent_upload_saved", agent_id=agent_id, size=saved.size)
    return saved
