
import asyncio
import sqlite3
from typing import Optional, Union

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from src.api import projects_service
from src.api.projects_service import ProjectKey
from src.config import settings
from src.models import (
    CheckProjectRootRequest,
    CreateProjectRequest,
    ProjectResponse,
    SuccessResponse,
    UpdateProjectRequest,
)

from src.api.auth import require_auth
from src.core.project_pack import store as project_pack_store
from src.core.project_pack.constants import BUSY_STATES, STATE_UNPACKED as PACK_STATE_UNPACKED
from src.core.companies import hero_images, store as companies_store
from src.core.session_roles import check as session_roles_check
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter()


@router.get("/projects", response_model=list[ProjectResponse], dependencies=[Depends(require_auth)])
async def get_projects(
    include_archived: bool = Query(
        False,
        description=(
            "Include ARCHIVED projects alongside the live ones. Defaults "
            "false, so a client that predates archiving sees exactly the "
            "list it saw before. Archived rows are not a separate list "
            "and there is no separate endpoint for them: they arrive "
            "mixed in, each carrying its own archived_at, so the client "
            "distinguishes them per row rather than by remembering which "
            "request it made."
        ),
    ),
):
    """
    Get the project list from the AUTHORITATIVE source.

    feat/db-is-authoritative. This route used to read config.json. It now
    reads the ``projects`` table, which is keyed ``UNIQUE(root)`` and
    therefore returns ONE entry per unique folder - the fix for the
    launcher drawing three nodes for
    ``/Users/sam/Development/ses_ec5bf2a3`` and expanding the same
    two child sessions under each of them.

    Each row now carries its ``id``, so the launcher attaches child
    sessions by row id straight from this response instead of looking the
    id up in a second request keyed by raw path - the lookup that made
    duplicate-path entries share children in the first place.

    THREE OUTCOMES, and this route never collapses them:
      - the database answered: rows served, authoritative;
      - the database is unreachable: config.json's entries are served,
        deduplicated by root, and GET /projects/authority reports
        ``mode: config_fallback`` with writes refused;
      - the database is readable but empty while config.json is not:
        the list is EMPTY and the mode says ``db_unreadable``, so an
        empty list is never rendered as "you have no projects" when it
        actually means "nothing could be read".

    A client that needs to know WHICH of those it is calls
    GET /projects/authority. This route always returns a list, because a
    launcher that cannot draw anything is a worse failure than one that
    draws the user's projects with a banner over them.

    Returns:
        list[ProjectResponse] - never raises for a datastore fault.
    """
    def _read_projects():
        v = projects_service.current_view(settings, include_archived=include_archived)
        return v, projects_service.views_to_responses(v, ProjectResponse)

    view, responses = await asyncio.to_thread(_read_projects)

    if view.degraded:
        logger.warning(
            "projects_served_degraded",
            mode=view.mode,
            detail=view.detail,
            count=len(view.projects),
        )
    else:
        logger.debug("projects_retrieved", count=len(view.projects))

    return responses


@router.get("/projects/authority", dependencies=[Depends(require_auth)])
async def get_projects_authority() -> dict:
    """
    Report where the project list came from, and whether writes work.

    Projects live in cloude.db and nowhere else, so this route no longer
    reports a disagreement between two sources - there is only one.
    ``mode`` is one of:

      ``db``             the normal case. The list is the table's and
                         writes are allowed. An empty list here is a
                         real, measured empty list.
      ``db_unreadable``  cloude.db could not be read. The list is EMPTY
                         because nothing could be read, NOT because
                         nothing is there, and ``message`` says so in
                         words. Writes are refused until it clears.

    ``reconcile`` reports what the last startup pass did to the table,
    so a repair the user did not ask for is still something the user can
    see.

    Returns:
        dict - ``{"mode", "writable", "degraded", "message", "detail",
        "project_count", "reconcile"}``.
    """
    return projects_service.authority_payload(settings)


@router.post("/projects/check-root", dependencies=[Depends(require_auth)])
async def check_project_root(body: CheckProjectRootRequest):
    """
    Ask whether a folder may be a project's root, writing nothing (#1928).

    The new-project flow calls this BEFORE it creates the session, so a refused folder
    (the projects base folder or one holding live projects, any letter case) leaves no
    loose session behind. It runs the same guard ``POST /projects`` runs.

    Args:
        body: ``{path}`` - the folder the project would live in.

    Returns:
        ``{"ok": true}``.

    Raises:
        HTTPException 409 (code project_root_refused): the folder is refused.
    """
    from contextlib import closing

    from src.core.project_store import normalize_root
    from src.core.project_writes import ProjectRootRefused, refuse_unsafe_root

    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            refuse_unsafe_root(conn, normalize_root(body.path))
    except ProjectRootRefused as e:
        logger.warning("project_root_check_refused", path=body.path, error=str(e))
        return JSONResponse(status_code=409, content={"detail": str(e), "code": ProjectRootRefused.CODE})
    return {"ok": True}


@router.post("/projects", response_model=ProjectResponse, status_code=201, dependencies=[Depends(require_auth)])
async def create_project(body: CreateProjectRequest) -> Union[JSONResponse, ProjectResponse]:
    """
    Add a new project.

    Writes the ``projects`` table, which is the only place projects
    live. There is no second store to keep in step.

    Args:
        body: Project creation parameters.

    Returns:
        Created project object.

    Raises:
        HTTPException 400: a project with that display name already exists.
        HTTPException 404: ``company_id`` names no company (nothing is created).
        HTTPException 409 (code project_root_refused): the folder is the projects base folder or holds live projects.
        HTTPException 409: a project already exists at that folder. This
            is the refusal that keeps the launcher showing one node per
            folder; it is 409 rather than 400 because the request is
            well-formed and the conflict is with existing state.
        HTTPException 503: cloude.db is unreachable, so the write is
            refused rather than being applied to config.json alone.
    """
    from contextlib import closing

    from src.core.project_writes import (
        ProjectNameConflict,
        ProjectRootConflict,
        ProjectRootRefused,
        create_project as db_create_project,
    )

    projects_service.guard_writable(settings)

    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            company = _company_or_404(conn, body.company_id)
            row = db_create_project(
                conn,
                name=body.name,
                path=body.path,
                description=body.description,
            )
            if company is not None:
                companies_store.assign_project(conn, row["id"], company["id"])
    except ProjectRootConflict as e:
        logger.warning("project_creation_root_conflict", path=body.path, error=str(e))
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(e),
                "existing_project": {"id": e.existing_id, "name": e.existing_name},
            },
        )
    except ProjectRootRefused as e:
        logger.warning("project_creation_root_refused", path=body.path, error=str(e))
        return JSONResponse(status_code=409, content={"detail": str(e), "code": ProjectRootRefused.CODE})
    except ProjectNameConflict as e:
        logger.warning("project_creation_failed_validation", error=str(e))
        raise api_error(400, "project_invalid", e, step="create_project") from e

    logger.info("project_created", name=row["display_name"], path=row["raw_path"])

    return ProjectResponse(
        id=row["id"],
        name=row["display_name"],
        path=row["raw_path"],
        description=row["description"],
        root=row["root"],
        default_launch_profile=row["default_agent_type"],
        company_id=company["id"] if company else None,
        company_name=company["name"] if company else None,
    )


def _company_or_404(conn: sqlite3.Connection, company_id: Optional[int]) -> Optional[dict]:
    if company_id is None:
        return None
    try:
        return companies_store.get_company(conn, company_id)
    except companies_store.CompanyNotFound:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")


@router.delete("/projects/{project_name}", response_model=SuccessResponse, dependencies=[Depends(require_auth)])
async def delete_project(project_name: str, request: Request) -> SuccessResponse:
    """Delete the project with this display name (see :func:`delete_project_for`)."""
    return await delete_project_for(project_name, request)


async def delete_project_for(project_name: ProjectKey, request: Request) -> SuccessResponse:
    from contextlib import closing

    from src.core.swarm import project_removal
    from src.core.swarm.body import BodyError
    from src.core.project_writes import delete_project as db_delete_project

    projects_service.guard_writable(settings)

    with closing(projects_service.open_db_or_503(settings)) as conn:
        target = projects_service.resolve_target(conn, project_name)
        if project_pack_store.state_of(conn, target["id"]) in BUSY_STATES:
            raise HTTPException(status_code=409, detail="a pack or unpack job is running on this project's folder")
        agents = project_removal.agents_to_turn_off(conn, target["id"])
        company_agent = project_removal.company_agent_id(conn, target["id"])
    try:
        await project_removal.turn_off_agents(request.app.state, target["id"], agents)
    except BodyError as exc:
        raise api_error(409, "swarm_refused", exc) from exc
    with closing(projects_service.open_db_or_503(settings)) as conn:
        db_delete_project(conn, target["id"])
    hero_images.remove(hero_images.PROJECT, target["id"])
    if company_agent is not None:
        await project_removal.tell_company(request.app.state, company_agent, target["display_name"])

    logger.info("project_deleted", name=target["display_name"], root=target["root"], agents_off=len(agents))
    await session_roles_check.after_change(request.app.state)

    return SuccessResponse(message=f"Project '{target['display_name']}' deleted successfully")


@router.patch(
    "/projects/{project_name}",
    response_model=ProjectResponse,
    dependencies=[Depends(require_auth)],
)
async def update_project(project_name: str, body: UpdateProjectRequest) -> ProjectResponse:
    """Update the project with this display name (see :func:`update_project_for`)."""
    return await update_project_for(project_name, body)


async def update_project_for(project_name: ProjectKey, body: UpdateProjectRequest) -> ProjectResponse:
    from contextlib import closing

    from src.core.launch_profiles import create_seam
    from src.core.project_writes import (
        ProjectColorInvalid,
        ProjectNameConflict,
        update_project as db_update_project,
    )

    if (
        body.new_name is None and body.description is None and body.short_description is None
        and body.default_launch_profile is None and body.color is None
    ):
        raise HTTPException(status_code=400, detail="No fields to update")

    default_profile = (body.default_launch_profile or "").strip()
    if default_profile and default_profile.lower() not in {
        i.lower() for i in create_seam.known_pick_ids(settings)
    }:
        raise HTTPException(status_code=400, detail={
            "code": "launch_profile_needed",
            "detail": f"no launch profile '{default_profile}'",
            "wrapper_options": create_seam.known_pick_ids(settings),
        })

    from src.core.descriptions.store import DescriptionInvalid, clean_text

    try:
        short_description = clean_text(body.short_description, single_line=True)
        description = clean_text(body.description, single_line=False)
    except DescriptionInvalid as exc:
        raise api_error(400, "project_invalid", exc, step="update_project") from exc

    projects_service.guard_writable(settings)

    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            target = projects_service.resolve_target(conn, project_name)
            row = db_update_project(
                conn,
                target["id"],
                new_name=body.new_name,
                description=description,
                short_description=short_description,
                default_agent_type=None if body.default_launch_profile is None else default_profile,
                color=body.color,
            )
    except ProjectColorInvalid as exc:
        raise api_error(422, "invalid_request", exc, step="update_project") from exc
    except ProjectNameConflict:
        logger.warning(
            "project_update_name_conflict",
            old_name=target["display_name"],
            new_name=body.new_name,
        )
        raise HTTPException(
            status_code=409,
            detail=f"A project named '{body.new_name}' already exists",
        )

    logger.info(
        "project_updated",
        old_name=target["display_name"],
        new_name=row["display_name"],
        description_changed=body.description is not None,
        short_description_changed=body.short_description is not None,
    )

    return ProjectResponse(
        id=row["id"],
        name=row["display_name"],
        path=row["raw_path"],
        description=row["description"],
        short_description=row.get("short_description"),
        root=row["root"],
        default_launch_profile=row["default_agent_type"],
        color=row.get("color"),
        **hero_images.fields(hero_images.PROJECT, row["id"]),
    )


def _project_archive_response(row: dict, outcome: dict) -> ProjectResponse:
    return ProjectResponse(
        id=row["id"],
        name=row["display_name"],
        path=row["raw_path"],
        description=row["description"],
        root=row["root"],
        archived_at=row["archived_at"],
        sessions_archived=outcome.get("sessions_archived"),
        sessions_live=outcome.get("sessions_live"),
        sessions_restored=outcome.get("sessions_restored"),
        **hero_images.fields(hero_images.PROJECT, row["id"]),
    )


@router.post(
    "/projects/{project_name}/archive",
    response_model=ProjectResponse,
    dependencies=[Depends(require_auth)],
)
async def archive_project_route(project_name: str) -> ProjectResponse:
    """Archive the project with this display name (see :func:`archive_project_for`)."""
    return await archive_project_for(project_name)


async def archive_project_for(project_name: ProjectKey) -> ProjectResponse:
    from contextlib import closing

    from src.core.project_archive import archive_project_and_sessions

    projects_service.guard_writable(settings)

    with closing(projects_service.open_db_or_503(settings)) as conn:
        target = projects_service.resolve_target(conn, project_name)
        outcome = archive_project_and_sessions(conn, target["id"])
        changed = outcome["changed"]
        row = dict(
            conn.execute(
                "SELECT * FROM projects WHERE id = ?", (target["id"],)
            ).fetchone()
        )

    logger.info(
        "project_archive_requested",
        name=row["display_name"],
        root=row["root"],
        changed=changed,
        archived_at=row["archived_at"],
        **hero_images.fields(hero_images.PROJECT, row["id"]),
    )

    return _project_archive_response(row, outcome)


@router.post(
    "/projects/{project_name}/unarchive",
    response_model=ProjectResponse,
    dependencies=[Depends(require_auth)],
)
async def unarchive_project_route(project_name: str) -> ProjectResponse:
    """Restore the project with this display name (see :func:`unarchive_project_for`)."""
    return await unarchive_project_for(project_name)


async def unarchive_project_for(project_name: ProjectKey) -> ProjectResponse:
    from contextlib import closing

    from src.core.project_archive import unarchive_project_and_sessions

    projects_service.guard_writable(settings)

    with closing(projects_service.open_db_or_503(settings)) as conn:
        target = projects_service.resolve_target(conn, project_name)
        pack_state = project_pack_store.state_of(conn, target["id"])
        if pack_state != PACK_STATE_UNPACKED:
            raise HTTPException(status_code=409, detail=(
                f"this project's folder is {pack_state}: unpack it first (POST /projects/{{name}}/unpack), then unhide it"))
        outcome = unarchive_project_and_sessions(conn, target["id"])
        changed = outcome["changed"]
        row = dict(
            conn.execute(
                "SELECT * FROM projects WHERE id = ?", (target["id"],)
            ).fetchone()
        )

    logger.info(
        "project_unarchive_requested",
        name=row["display_name"],
        root=row["root"],
        changed=changed,
    )

    return _project_archive_response(row, outcome)
