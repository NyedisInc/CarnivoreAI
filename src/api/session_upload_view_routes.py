
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from src.api.auth import require_auth
from src.api.remote_route_guard import refuse_remote
from src.core.product_identity import LEGACY_UPLOAD_DIR_NAMES, UPLOAD_DIR_NAME

router = APIRouter()

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
BUCKETS = (UPLOAD_DIR_NAME, *LEGACY_UPLOAD_DIR_NAMES)


def resolve_upload_image(working_dir: str, path: str) -> Optional[str]:
    if not path or "\x00" in path or not os.path.isabs(path):
        return None
    if os.path.splitext(path)[1].lower() not in IMAGE_TYPES:
        return None
    base = os.path.realpath(os.path.expanduser(working_dir))
    real = os.path.realpath(path)
    if os.path.splitext(real)[1].lower() not in IMAGE_TYPES or not os.path.isfile(real):
        return None
    for name in BUCKETS:
        bucket = os.path.realpath(os.path.join(base, name))
        if bucket == os.path.join(base, name) and os.path.dirname(real) == bucket:
            return real
    return None


@router.get("/sessions/{session_id}/upload-image", dependencies=[Depends(require_auth)])
async def get_upload_image(session_id: str, path: str, request: Request) -> FileResponse:
    """Serve one picture the session's upload route saved. Output: the image bytes. Raises: 404 for anything else."""
    refuse_remote(request.app.state.session_manager, session_id, "an upload picture read")
    session = request.app.state.services.registry.get_session(session_id)
    real = resolve_upload_image(session.working_dir, path) if session and session.working_dir else None
    if real is None:
        raise HTTPException(status_code=404, detail="no such picture")
    return FileResponse(real, media_type=IMAGE_TYPES[os.path.splitext(real)[1].lower()], headers={"Cache-Control": "private, max-age=3600"})
