
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.api.error_response import refusal_error
from src.api import themes_routes
from src.api.auth import require_auth

logger = structlog.get_logger()

router = APIRouter(prefix="/themes", tags=["themes"])

THEME_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
_THEME_ID_RE = re.compile(THEME_ID_PATTERN)

MAX_THEME_JSON_BYTES = 256 * 1024


class ThemeExportRefused(Exception):

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _find_theme_dir(root: Optional[Path], theme_id: str) -> Optional[Path]:
    if root is None or not root.is_dir():
        return None
    try:
        return next((child for child in root.iterdir() if child.name == theme_id), None)
    except OSError as exc:
        logger.warning("theme_export_root_unreadable", root=str(root), error=str(exc))
        return None


def read_theme_document(theme_id: str, bundled: Path, user: Optional[Path]) -> Dict[str, Any]:
    if not _THEME_ID_RE.fullmatch(theme_id or ""):
        raise ThemeExportRefused(400, "bad_id", "that is not a theme id")
    theme_dir = _find_theme_dir(bundled, theme_id) or _find_theme_dir(user, theme_id)
    if theme_dir is None or not theme_dir.is_dir():
        raise ThemeExportRefused(404, "not_found", f"no theme named {theme_id}")
    manifest = theme_dir / "theme.json"
    if theme_dir.is_symlink() or manifest.is_symlink():
        raise ThemeExportRefused(409, "symlink", f"the theme {theme_id} is a symbolic link; refusing to export it")
    try:
        size = manifest.stat().st_size
        if size > MAX_THEME_JSON_BYTES:
            raise ThemeExportRefused(413, "too_large", f"theme.json is larger than {MAX_THEME_JSON_BYTES} bytes")
        raw = json.loads(manifest.read_bytes())
    except FileNotFoundError:
        raise ThemeExportRefused(404, "not_found", f"the theme {theme_id} has no theme.json")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("theme_export_unreadable", theme_id=theme_id, error=str(exc))
        raise ThemeExportRefused(422, "not_a_manifest", "theme.json could not be read as JSON")
    if not isinstance(raw, dict) or raw.get("id") != theme_id:
        raise ThemeExportRefused(422, "not_a_manifest", "theme.json does not name this theme")
    return raw


@router.get("/{theme_id}/export", dependencies=[Depends(require_auth)])
async def export_theme(theme_id: str) -> JSONResponse:
    """One theme's ``theme.json``, served as ``<id>.theme.json``.

    Output: the file's JSON object.
    Raises: HTTPException with ``{code, message}`` - see
      ``read_theme_document``.
    """
    try:
        document = read_theme_document(
            theme_id, themes_routes._bundled_themes_root(), themes_routes._user_themes_root()
        )
    except ThemeExportRefused as exc:
        raise refusal_error(exc, theme_id=theme_id) from exc
    return JSONResponse(
        document,
        headers={
            "Content-Disposition": f'attachment; filename="{theme_id}.theme.json"',
            "Cache-Control": "no-store",
        },
    )
