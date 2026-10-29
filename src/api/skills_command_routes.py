"""``GET /api/v1/skills/command-center``: every local skill against every project and the personal folders.

Read only except ``POST /skills/copy`` and ``POST /skills/remove``. The client names no path; columns come from the launcher's own project list and the fixed personal
folders (``src/core/skill_manager/command_center.py``). Mounted under ``/api/v1`` from ``src/api/routes.py``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.skills_manager_routes import _codex_home, _profiles
from src.core import session_change_notice
from src.core.project_authority import MODE_DB, resolve_projects
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS
from src.core.skill_manager.command_center import build_command_center
from src.core.skill_manager.copy_skill import CopyError, copy_skill
from src.core.skill_manager.remove_cell import remove_cell
from src.core.skill_manager.types import OverrideError
from src.core.skills.installer import trash_stamp
from src.models.websocket import WSMessageType

logger = structlog.get_logger()
router = APIRouter(tags=["skills"])


def _ledger_paths(request: Request) -> Iterator[Tuple[str, str]]:
    with request.app.state.services.catalog.ledger() as ledger:
        for row in ledger.list():
            for target in ledger.targets(row.install_id):
                yield str(target.path), row.item_id


def command_center_now(request: Request, include_archived: bool) -> Dict[str, Any]:
    """Build the matrix on a worker thread (project list, filesystem and ledger reads).

    Raises: HTTPException(503) when the project list could not be read (an empty matrix would lie).
    """
    state_dir = request.app.state.services.settings_reader.state_dir()
    view = resolve_projects(state_dir, include_archived=include_archived)
    if view.mode != MODE_DB:
        raise HTTPException(status_code=503, detail="the project list could not be read, so the command center cannot be built")
    home = Path.home()
    return build_command_center(
        profiles=_profiles(home),
        projects=view.projects,
        home=home,
        codex_home=_codex_home(home),
        read_ledger=lambda: list(_ledger_paths(request)),
        include_archived=include_archived,
    )


@router.get("/skills/command-center", dependencies=[Depends(require_auth)])
async def get_command_center(request: Request, include_archived: bool = False) -> Dict[str, Any]:
    """Every local skill against every non-archived project plus the personal skills folders.

    Inputs: include_archived - also list archived projects, as read-only columns.
    Output: {generation, include_archived, columns[], rows[]}; see ``docs/skills-manager.md``.
    Raises: HTTPException(503) when the project list could not be read.
    """
    return await asyncio.to_thread(command_center_now, request, include_archived)


class CopyTarget(BaseModel):
    """One target of a copy: a column id from the matrix, and whether to replace a same-named folder there."""

    column_id: str
    replace: bool = False


class CopyRequest(BaseModel):
    """Body of ``POST /skills/copy``. No field is a filesystem path; ids come from the command center matrix."""

    source_location_id: str
    source_column_id: str
    targets: List[CopyTarget] = Field(min_length=1, max_length=50)
    dry_run: bool = True
    generation: Optional[str] = Field(default=None, description="the matrix generation the caller saw; required for a real copy")
    source_digest: Optional[str] = Field(default=None, description="the dry run's source_digest; required for a real copy")
    include_archived: bool = False


@router.post("/skills/copy", dependencies=[Depends(require_auth)])
async def post_copy(request: Request, body: CopyRequest) -> Dict[str, Any]:
    """Copy one local skill folder into other projects or the personal skills folders (dry run by default).

    Inputs: the body (ids from GET /skills/command-center; ``include_archived`` must match the view the ids came from).
    Output: {dry_run, generation, source{..., source_digest, scripts, exec_files}, results[{column_id, status, ...}]};
      statuses copied, replaced, would_copy, would_replace, skipped, refused, use_catalog_install, use_catalog_uninstall.
    Raises: HTTPException 400 ``stale_check_required``; 404 unknown source or target; 409 with ``{"code", "detail"}``
      for stale, symlink_in_skill, too_large, target_unsafe; 503 when the project list could not be read.
    """
    stamp = trash_stamp(request.app.state.services.clock)

    def work() -> Dict[str, Any]:
        matrix = command_center_now(request, body.include_archived)
        return copy_skill(
            matrix, source_location_id=body.source_location_id, source_column_id=body.source_column_id,
            targets=[t.model_dump() for t in body.targets], dry_run=body.dry_run, generation=body.generation,
            source_digest=body.source_digest, home=Path.home(), stamp=stamp,
        )

    try:
        return await asyncio.to_thread(work)
    except CopyError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})


class RemoveCellRequest(BaseModel):
    """Body of ``POST /skills/remove``. No field is a filesystem path; ids come from the command center matrix."""

    location_id: str
    column_id: str
    generation: str
    include_archived: bool = False


@router.post("/skills/remove", dependencies=[Depends(require_auth)])
async def post_remove(request: Request, body: RemoveCellRequest) -> Dict[str, Any]:
    """Move one skill folder from a command center cell into its root's trash (never a delete).

    Inputs: the body (ids and ``generation`` from GET /skills/command-center; ``include_archived`` must match that view).
    Output: {name, folder, label, harness, location_id, trashed_to}.
    Raises: HTTPException 400 ``stale_check_required``; 404 ``unknown_cell`` or ``gone``; 409 with ``{"code", "detail"}``
      for stale, read_only, use_catalog_uninstall, target_unsafe, trash_name_taken, not_a_skill_folder; 500 when the move
      failed; 503 when the project list could not be read.
    """
    stamp = trash_stamp(request.app.state.services.clock)

    def work() -> Dict[str, Any]:
        matrix = command_center_now(request, body.include_archived)
        return remove_cell(matrix, location_id=body.location_id, column_id=body.column_id, generation=body.generation, stamp=stamp)

    try:
        result = await asyncio.to_thread(work)
    except OverrideError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})
    except OSError as exc:
        logger.warning("skill_cell_remove_failed", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="the folder could not be moved to the trash")
    logger.info("skill_cell_removed", column_id=body.column_id)
    session_change_notice.publish(
        request.app.state, {"type": WSMessageType.SKILLS_CHANGED, "harness": result["harness"], "file": "location"}
    )
    notifier.notify(LOCAL_SKILLS)
    return result
