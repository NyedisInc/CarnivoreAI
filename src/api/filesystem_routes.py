
from fastapi import APIRouter, Depends, HTTPException
from pathlib import Path
from src.api.auth import require_auth
from src.config import settings
from src.models import BrowseResponse, DirectoryEntry, MkdirRequest
from src.api.error_response import api_error
from typing import List, Optional

router = APIRouter()


def _build_browse_response(resolved: Path) -> BrowseResponse:
    entries: List[DirectoryEntry] = []
    try:
        for child in sorted(resolved.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith('.'):
                continue
            try:
                if child.is_dir():
                    entries.append(DirectoryEntry(name=child.name, path=str(child)))
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise api_error(403, "directory_forbidden", None, path=str(resolved))
    except OSError as e:
        raise api_error(500, "directory_unreadable", e, path=str(resolved)) from e

    parent = str(resolved.parent) if resolved.parent != resolved else None

    return BrowseResponse(
        path=str(resolved),
        parent=parent,
        entries=entries,
    )


@router.get("/filesystem/browse", response_model=BrowseResponse, dependencies=[Depends(require_auth)])
async def browse_directory(path: Optional[str] = None):
    """
    List subdirectories of a given filesystem path for the project folder picker.

    Args:
        path: Directory path to list. Defaults to the configured default working dir,
              or the user's home directory if that is unavailable.

    Returns:
        BrowseResponse with the absolute path, its parent, and subdirectories.

    Raises:
        HTTPException: 404 if the path does not exist or is not a directory,
                       403 if permission denied. The frontend folder picker
                       relies on a clean 404 to decide whether to auto-create.
    """
    import os
    from pathlib import Path

    if path:
        target = Path(path).expanduser()
    else:
        try:
            target = settings.get_working_dir()
        except Exception:
            target = Path.home()

    try:
        resolved = target.resolve(strict=False)
    except Exception as e:  # noqa: BLE001
        raise api_error(400, "path_invalid", e) from e

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {resolved}")

    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {resolved}")

    return _build_browse_response(resolved)


@router.post("/filesystem/mkdir", response_model=BrowseResponse, dependencies=[Depends(require_auth)])
async def make_directory(body: MkdirRequest):
    """
    Create a directory (``mkdir -p``) and return its listing in one round-trip.

    Resolves the requested path (``~`` is expanded), creates it along with any
    missing parents, then lists it exactly like ``browse_directory`` so the
    folder picker can navigate straight into the new directory. ``mkdir -p``
    semantics make this idempotent - it succeeds if the directory already
    exists. Matches the browse endpoint's path handling (resolve, no root
    restriction).

    Raises:
        HTTPException: 400 on an invalid path or any OS error (e.g. permission
                       denied, a file already occupies the path), 403 if the
                       created directory cannot be read.
    """
    target = Path(body.path).expanduser()

    try:
        resolved = target.resolve(strict=False)
    except Exception as e:  # noqa: BLE001
        raise api_error(400, "path_invalid", e) from e

    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise api_error(400, "directory_create_failed", e, path=str(resolved)) from e

    return _build_browse_response(resolved)
