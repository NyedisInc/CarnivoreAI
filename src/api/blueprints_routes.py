
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Callable, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from src.api.error_response import soft_failure
from src.api import blueprints_launch_routes
from src.api.blueprints_settings import CaptureSources
from src.api.auth import require_auth
from src.config import settings
from src.core import blueprints_file, blueprints_store as store
from src.core import blueprints_shape, project_worktree
from src.core.layouts import store as layouts_store
from src.core import session_change_notice
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.skills.project_scope import ProjectPathRefused, resolve_project_path
from src.models.blueprints import (
    FAMILY_RE, LABEL_MAX, BlueprintModel, BlueprintSpec, BlueprintWriteRequest,
    BlueprintsResponse, ExportResponse, FromLayoutRequest, ProjectFileRequest, WorktreeSettings,
)
from src.models.model_ids import is_valid_model_id

logger = structlog.get_logger()

router = APIRouter(prefix="/blueprints", tags=["blueprints"])

NOTICE_REASON = "blueprints"


def db_path():
    return db_path_for(settings.get_state_dir())


def error(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    body: Dict[str, Any] = {"code": code, "detail": detail}
    body.update(extra)
    return HTTPException(status_code=status, detail=body)


def to_model(saved: store.SavedBlueprint) -> BlueprintModel:
    return BlueprintModel(blueprint_uuid=saved.blueprint_uuid, name=saved.name, spec=saved.spec,
                          created_at=saved.created_at, updated_at=saved.updated_at)


def run(operation: Callable, *args: Any, **kwargs: Any) -> Any:
    with closing(connect(db_path(), create=False)) as conn:
        return operation(conn, *args, **kwargs)


async def call(operation: Callable, *args: Any, **kwargs: Any) -> Any:
    try:
        return await run_in_threadpool(run, operation, *args, **kwargs)
    except store.BlueprintNotFound as exc:
        raise error(404, "blueprint_not_found", str(exc))
    except store.BlueprintNameTaken as exc:
        raise error(409, "blueprint_name_taken", str(exc))
    except store.BlueprintLimitReached as exc:
        raise error(409, "blueprint_limit", str(exc))
    except store.BlueprintCorrupt as exc:
        raise error(409, "blueprint_corrupt", str(exc))
    except store.BlueprintSecret as exc:
        raise error(400, "blueprint_secret", str(exc), detectors=exc.detectors)
    except (DatastoreUnreadableError, store.BlueprintsUnavailable) as exc:
        raise error(503, "blueprints_unavailable", str(exc))
    except OSError as exc:
        logger.warning("blueprints_write_failed", error=str(exc))
        raise error(503, "blueprints_unavailable", str(exc))
    except ValueError as exc:
        raise error(400, "blueprint_invalid", str(exc))


def announce(request: Request) -> None:
    session_change_notice.publish(
        request.app.state, session_change_notice.build_structural_notice(NOTICE_REASON))


async def project_root(request: Request, raw: str) -> str:
    services = request.app.state.services
    try:
        return await asyncio.to_thread(resolve_project_path, raw, roots=services.install_roots,
                                       state_dir=services.settings_reader.state_dir())
    except ProjectPathRefused as exc:
        raise error(409, "project_path_invalid", exc.detail)


@router.get("", response_model=BlueprintsResponse, dependencies=[Depends(require_auth)])
async def list_blueprints() -> BlueprintsResponse:
    """Every blueprint by name, or an explicit CANNOT DETERMINE (still 200)."""
    if not db_path().exists():
        return BlueprintsResponse(status="unavailable", detail="datastore has not been created yet")
    try:
        saved: List[store.SavedBlueprint] = await run_in_threadpool(run, store.list_blueprints)
    except (DatastoreUnreadableError, store.BlueprintError, OSError) as exc:
        return BlueprintsResponse(status="unavailable", detail=soft_failure("datastore_unavailable", exc, step="list_blueprints"))
    return BlueprintsResponse(status="ok", blueprints=[to_model(b) for b in saved])


@router.post("", response_model=BlueprintModel, dependencies=[Depends(require_auth)])
async def create_blueprint(body: BlueprintWriteRequest, request: Request) -> BlueprintModel:
    """Store a new blueprint. Raises HTTPException 400, 409, 503."""
    saved = await call(store.create_blueprint, body.spec)
    announce(request)
    return to_model(saved)


@router.get("/settings", response_model=WorktreeSettings, dependencies=[Depends(require_auth)])
async def get_settings() -> WorktreeSettings:
    """Where a launch makes new worktrees (``~/dev-worktrees`` unless set)."""
    return WorktreeSettings(worktree_root=blueprints_launch_routes.worktree_root())


@router.put("/settings", response_model=WorktreeSettings, dependencies=[Depends(require_auth)])
async def put_settings(body: WorktreeSettings) -> WorktreeSettings:
    """Store the worktree root through the one config writer.

    Raises: HTTPException 400 ``worktree_root_invalid``, 503 when config.json
      cannot be written.
    """
    try:
        stored = await asyncio.to_thread(project_worktree.set_root, settings.auth_config_file,
                                         body.worktree_root)
    except project_worktree.WorktreeRefused as exc:
        raise error(400, exc.code, exc.detail)
    except (FileNotFoundError, ValueError) as exc:
        raise error(503, "settings_unavailable", str(exc))
    return WorktreeSettings(worktree_root=stored)


@router.post("/import", response_model=BlueprintModel, dependencies=[Depends(require_auth)])
async def import_blueprint(body: ProjectFileRequest, request: Request) -> BlueprintModel:
    """Store the spec in ``<project>/.carnivore/swarm.json`` as a new blueprint.

    Description: the file is validated strictly (unknown fields, caps, the
      model guard, the prompt rules) and a malformed one is refused with
      what is wrong and where. ``name`` stores it under another name.
    Raises: HTTPException 404 ``swarm_file_missing``, 409 (invalid file,
      unsafe path, project, name taken), 400 (secret), 503.
    """
    root = await project_root(request, body.project_path)
    try:
        spec = await asyncio.to_thread(blueprints_file.read_swarm, root)
    except blueprints_file.SwarmFileError as exc:
        raise error(404 if exc.code == "swarm_file_missing" else 409, exc.code, exc.detail)
    if body.name is not None:
        try:
            spec = BlueprintSpec.model_validate({**spec.model_dump(mode="json"), "name": body.name})
        except ValidationError as exc:
            raise error(400, "blueprint_invalid", str(exc.errors(include_url=False,
                                                                 include_input=False)[0]["msg"]))
    saved = await call(store.create_blueprint, spec)
    announce(request)
    return to_model(saved)


def _layout_spec(conn: Any, layout_uuid: str, name: str, sources: Any = None) -> BlueprintSpec:
    layout = layouts_store.get_layout(conn, layout_uuid)
    sessions: List[Dict[str, Any]] = []
    labels: List[str] = []
    for member in layout.members:
        row = conn.execute("SELECT title, claude_title, tmux_name, agent_type, agent_family, "
                           "model, working_dir, notifications_muted FROM sessions WHERE id = ?",
                           (member.session_row_id,)).fetchone()
        if row is None or not row["working_dir"]:
            raise ValueError(f"member {member.session_uuid} has no recorded folder")
        base = (row["title"] or row["claude_title"] or row["tmux_name"] or "session").strip()
        base = base[: LABEL_MAX - 4] or "session"
        label, n = base, 2
        while label.casefold() in labels:
            label, n = f"{base} {n}", n + 1
        labels.append(label.casefold())
        family = next((f for f in (row["agent_type"], row["agent_family"])
                       if f and FAMILY_RE.match(f)), "claude")
        model = row["model"] if row["model"] and is_valid_model_id(row["model"]) else None
        sessions.append({"label": label, "family": family, "model": model,
                         "folder": {"mode": "existing", "path": row["working_dir"]},
                         "session_uuid": member.session_uuid,
                         **(sources.member_fields(row, member.session_uuid) if sources else {})})
    template = blueprints_shape.template_from_layout(
        layout.shape, [m.session_row_id for m in layout.members])
    return BlueprintSpec.model_validate(
        {"name": name or layout.name, "shape_template": template, "sessions": sessions})


def _create_from_layout(conn: Any, layout_uuid: str, name: str, sources: Any = None) -> store.SavedBlueprint:
    return store.create_blueprint(conn, _layout_spec(conn, layout_uuid, name, sources))


@router.post("/from-layout/{layout_uuid}", response_model=BlueprintModel,
             dependencies=[Depends(require_auth)])
async def blueprint_from_layout(layout_uuid: str, body: FromLayoutRequest,
                                request: Request) -> BlueprintModel:
    """Save a Layout's members as a blueprint ("save as blueprint").

    Raises: HTTPException 404 ``layout_not_found``, 409 (name taken,
      ``layout_member_unusable``), 400, 503.
    """
    try:
        saved = await call(_create_from_layout, layout_uuid, (body.name or "").strip(),
                           await CaptureSources.read(request))
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code") == "blueprint_invalid":
            raise error(409, "layout_member_unusable", exc.detail["detail"])
        raise
    except layouts_store.LayoutNotFound as exc:
        raise error(404, "layout_not_found", str(exc))
    except (layouts_store.LayoutsUnavailable, ValidationError) as exc:
        raise error(409, "layout_member_unusable", str(exc))
    announce(request)
    return to_model(saved)


@router.get("/{blueprint_uuid}", response_model=BlueprintModel,
            dependencies=[Depends(require_auth)])
async def get_blueprint(blueprint_uuid: str) -> BlueprintModel:
    """One blueprint. Raises HTTPException 404, 409 (corrupt), 503."""
    return to_model(await call(store.get_blueprint, blueprint_uuid))


@router.put("/{blueprint_uuid}", response_model=BlueprintModel,
            dependencies=[Depends(require_auth)])
async def replace_blueprint(blueprint_uuid: str, body: BlueprintWriteRequest,
                            request: Request) -> BlueprintModel:
    """Replace a blueprint's whole spec. Raises HTTPException 400, 404, 409, 503."""
    saved = await call(store.replace_blueprint, blueprint_uuid, body.spec)
    announce(request)
    return to_model(saved)


@router.delete("/{blueprint_uuid}", dependencies=[Depends(require_auth)])
async def delete_blueprint(blueprint_uuid: str, request: Request) -> Dict[str, bool]:
    """Delete a blueprint. No session, Layout, project or swarm file is touched."""
    await call(store.delete_blueprint, blueprint_uuid)
    announce(request)
    return {"deleted": True}


@router.post("/{blueprint_uuid}/export", response_model=ExportResponse,
             dependencies=[Depends(require_auth)])
async def export_blueprint(blueprint_uuid: str, body: ProjectFileRequest,
                           request: Request) -> ExportResponse:
    """Write the spec to ``<project>/.carnivore/swarm.json``, atomically.

    Raises: HTTPException 404, 409 (project, unsafe path), 400 (secret), 503.
    """
    saved = await call(store.get_blueprint, blueprint_uuid)
    root = await project_root(request, body.project_path)
    try:
        path = await asyncio.to_thread(blueprints_file.write_swarm, root, saved.spec)
    except blueprints_file.SwarmFileError as exc:
        raise error(503 if exc.code == "swarm_write_failed" else 409, exc.code, exc.detail)
    except store.BlueprintSecret as exc:
        raise error(400, "blueprint_secret", str(exc), detectors=exc.detectors)
    logger.info("blueprint_exported", blueprint_uuid=blueprint_uuid)
    return ExportResponse(path=str(path), blueprint_uuid=blueprint_uuid)


router.include_router(blueprints_launch_routes.router)
