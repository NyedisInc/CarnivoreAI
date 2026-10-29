
from __future__ import annotations

import re
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.api.auth import require_auth
from src.core.version import repo_root

logger = structlog.get_logger()

router = APIRouter(tags=["features"])

_FEATURE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_MEDIA_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|webp|gif|svg)$")

_CONTENT_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


def _media_root() -> Path:
    return repo_root() / "features" / "media"


@router.get("/feature-media/{feature_id}/{filename}", dependencies=[Depends(require_auth)])
async def get_feature_media(feature_id: str, filename: str) -> FileResponse:
    """Serve one media file belonging to one catalog feature.

    Description: refuses (404) before touching the filesystem when either
      path segment fails its allowlist, and again after resolving the
      joined path when it does not land inside this feature's own media
      directory. The response type is decided by the file's own
      extension, matched against the fixed table above - never by
      anything the client sent.
    Inputs: feature_id (str) - a catalog id, e.g. ``sidebar-help-panel``.
      filename (str) - a plain name inside that feature's media folder,
      e.g. ``panel.png``.
    Output: FileResponse - the bytes, typed from the extension.
    Raises: HTTPException(404) for an invalid segment, a missing feature,
      a missing file, or a path that resolves outside its own folder.
    Example: GET /api/v1/feature-media/sidebar-help-panel/panel.png
    """
    if not _FEATURE_ID_RE.match(feature_id) or not _MEDIA_FILENAME_RE.match(filename):
        logger.info(
            "feature_media_path_refused", feature_id=feature_id, filename=filename
        )
        raise HTTPException(status_code=404, detail="not found")

    folder = _media_root() / feature_id
    candidate = folder / filename

    try:
        folder_resolved = folder.resolve()
        candidate_resolved = candidate.resolve()
    except OSError:
        raise HTTPException(status_code=404, detail="not found")

    if (
        candidate.is_symlink()
        or folder_resolved != candidate_resolved.parent
        or not candidate_resolved.is_file()
    ):
        logger.info(
            "feature_media_not_found", feature_id=feature_id, filename=filename
        )
        raise HTTPException(status_code=404, detail="not found")

    media_type = _CONTENT_TYPES.get(candidate_resolved.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="not found")

    return FileResponse(
        candidate_resolved,
        media_type=media_type,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )
