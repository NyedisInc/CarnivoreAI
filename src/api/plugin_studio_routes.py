
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from src.api import catalog_publish_routes, session_crud_routes
from src.api.auth import require_auth
from src.api.error_response import refusal_error
from src.config import settings
from src.core.plugin_studio import (
    PluginStudioError,
    actions,
    dev_session,
    readiness,
    scaffolder,
    session_launcher,
    store,
)
from src.plugins.host import developer_mode
from src.plugins.host.peer_refusal import refuse_peer_token_writes

logger = structlog.get_logger()

router = APIRouter(
    prefix="/cplug-owner/studio",
    tags=["cplugs"],
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)


class CreateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: StrictStr = Field(..., min_length=1, max_length=4000)
    name: Optional[StrictStr] = Field(default=None, max_length=64)
    template: StrictStr = Field(default="python", max_length=32)
    agent_kind: Literal["claude", "codex", "agy"] = "claude"
    start_agent: StrictBool = True
    start_dev: StrictBool = False
    author: Optional[StrictStr] = Field(default=None, max_length=80)


class LaunchAgentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_kind: Literal["claude", "codex", "agy"] = "claude"
    prompt: Optional[StrictStr] = Field(default=None, max_length=4000)


class DevStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_approve: StrictBool = True


class ReadinessBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_tests: StrictBool = True
    handle: Optional[StrictStr] = Field(default=None, max_length=64)


class TestSandboxBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_only: StrictBool = False
    smoke_only: StrictBool = False


class InstallWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activate_runtime: StrictBool = True
    auto_approve: StrictBool = True


class PublishWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["local", "github"] = "local"
    repo: Optional[StrictStr] = Field(default=None, max_length=150)
    tag: Optional[StrictStr] = Field(default=None, max_length=255)
    pointer: Optional[StrictStr] = Field(default=None, max_length=400)
    commit_sha: Optional[StrictStr] = Field(default=None, max_length=40)
    subdir: Optional[StrictStr] = Field(default=None, max_length=512)
    version: Optional[StrictStr] = Field(default=None, max_length=64)
    digest: Optional[StrictStr] = Field(default=None, max_length=64)
    dry_run: StrictBool = True
    include_workspace_files: StrictBool = False


class PreviewRenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme_id: Optional[StrictStr] = Field(default=None, max_length=64)
    width: Optional[StrictInt] = Field(default=None, ge=120, le=3840)
    height: Optional[StrictInt] = Field(default=None, ge=80, le=2160)
    surface_id: Optional[StrictStr] = Field(default=None, max_length=64)


def _state_dir(request: Request) -> Path:
    live = getattr(request.app.state, "sidecar_runtime", None)
    if live is not None and getattr(live, "state_dir", None) is not None:
        return Path(live.state_dir)
    return Path(settings.get_state_dir())


def _http_err(exc: PluginStudioError) -> HTTPException:
    return refusal_error(exc, extra=exc.extra or None)


def _session_status_of(request: Request, session_id: Optional[str]) -> Dict[str, Any]:
    if not session_id:
        return {"session_id": None, "active": False, "status": "none"}
    mgr = getattr(request.app.state, "session_manager", None)
    if mgr is None:
        return {"session_id": session_id, "active": False, "status": "unknown"}
    row = None
    with contextlib.suppress(Exception):
        if hasattr(mgr, "get_session"):
            row = mgr.get_session(session_id)
        elif hasattr(mgr, "sessions") and isinstance(mgr.sessions, dict):
            row = mgr.sessions.get(session_id)
    if row is None:
        return {"session_id": session_id, "active": False, "status": "not_found"}
    status_val = getattr(row, "status", None) or (row.get("status") if isinstance(row, dict) else "active")
    tmux_val = getattr(row, "tmux_session", None) or (row.get("tmux_session") if isinstance(row, dict) else None)
    return {
        "session_id": session_id,
        "active": str(status_val) not in ("closed", "dead", "stopped"),
        "status": str(status_val or "active"),
        "tmux_session": tmux_val,
    }


@router.get("/workspaces")
async def list_workspaces(request: Request) -> Dict[str, Any]:
    """List all Plugin Studio workspaces recorded in ``workspaces.json``."""
    state_dir = _state_dir(request)
    try:
        items = await asyncio.to_thread(store.list_workspaces, state_dir)
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
    return {"workspaces": items}


@router.post("/workspaces", status_code=201)
async def create_workspace(body: CreateWorkspaceBody, request: Request) -> Dict[str, Any]:
    """Scaffold a v2 plugin workspace and optionally launch an agent session + live dev watcher."""
    state_dir = _state_dir(request)
    try:
        if body.start_agent:
            session_launcher.resolve_agent_type(body.agent_kind)
        if body.start_dev and not developer_mode.is_on():
            raise HTTPException(
                status_code=409,
                detail={"code": "developer_mode_off", "detail": "Developer mode is off; enable Developer Mode in settings first."},
            )
        workspace, files = await asyncio.to_thread(
            scaffolder.create_workspace,
            state_dir,
            prompt=body.prompt,
            template=body.template,
            name=body.name,
            agent_kind=body.agent_kind,
            author=body.author or "me",
        )
    except PluginStudioError as exc:
        raise _http_err(exc) from exc

    studio_id = workspace["studio_id"]
    session_info: Optional[Dict[str, Any]] = None
    dev_info: Optional[Dict[str, Any]] = None

    try:
        if body.start_agent:
            session_info = await session_launcher.launch_agent_session(
                workspace,
                agent_kind=body.agent_kind,
                session_creator=lambda req: session_crud_routes.create_session_with_extra(request, req),
            )
            workspace = await asyncio.to_thread(
                store.update_workspace,
                state_dir,
                studio_id,
                lambda row: {
                    **row,
                    "session_id": session_info["session_id"],
                    "session_tmux": session_info.get("tmux_session"),
                },
            )
        if body.start_dev:
            mgr = dev_session.manager_for(request.app)
            dev_info = await mgr.start(studio_id, workspace, auto_approve=True)
            workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
    except HTTPException:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(scaffolder.delete_workspace_dir, state_dir, workspace)
            await asyncio.to_thread(store.remove_workspace, state_dir, studio_id)
        raise
    except PluginStudioError as exc:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(scaffolder.delete_workspace_dir, state_dir, workspace)
            await asyncio.to_thread(store.remove_workspace, state_dir, studio_id)
        raise _http_err(exc) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("studio_create_workspace_failed", studio_id=studio_id, error_type=type(exc).__name__, exc_info=True)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(scaffolder.delete_workspace_dir, state_dir, workspace)
            await asyncio.to_thread(store.remove_workspace, state_dir, studio_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "studio_create_failed", "detail": "Failed to initialize Plugin Studio workspace."},
        ) from exc

    return {
        "workspace": workspace,
        "files": files,
        "session": session_info,
        "dev": dev_info,
    }


@router.get("/workspaces/{studio_id}")
async def get_workspace(studio_id: str, request: Request) -> Dict[str, Any]:
    """Return workspace metadata, files, session status, dev status, inspector snapshot, and preview."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        folder = store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        files = await asyncio.to_thread(store.list_workspace_files, folder)
        mgr = dev_session.manager_for(request.app)
        dev_status = mgr.status_for(studio_id, state_dir, workspace.get("plugin_id"))
        inspector = await mgr.get_inspector_snapshot(studio_id, workspace)
        preview = await mgr.preview_render(studio_id, workspace)
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
    return {
        "workspace": workspace,
        "files": files,
        "session_status": _session_status_of(request, workspace.get("session_id")),
        "dev_status": dev_status,
        "inspector": inspector,
        "preview": preview,
    }


@router.delete("/workspaces/{studio_id}")
async def delete_workspace(
    studio_id: str,
    request: Request,
    delete_files: bool = Query(default=True),
) -> Dict[str, Any]:
    """Stop any live Studio dev watcher/lease and delete the workspace record (and folder when ``delete_files=True``)."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        mgr = dev_session.manager_for(request.app)
        await mgr.stop(studio_id, workspace)
        removed = await asyncio.to_thread(store.remove_workspace, state_dir, studio_id)
        if delete_files:
            await asyncio.to_thread(scaffolder.delete_workspace_dir, state_dir, removed)
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
    return {"ok": True, "studio_id": studio_id}


@router.post("/workspaces/{studio_id}/agent")
async def launch_workspace_agent(
    studio_id: str,
    body: LaunchAgentBody,
    request: Request,
) -> Dict[str, Any]:
    """Launch a ``claude``, ``codex``, or ``agy`` coding session in the workspace."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        launched = await session_launcher.launch_agent_session(
            workspace,
            agent_kind=body.agent_kind,
            session_creator=lambda req: session_crud_routes.create_session_with_extra(request, req),
            prompt_override=body.prompt,
        )
        await asyncio.to_thread(
            store.update_workspace,
            state_dir,
            studio_id,
            lambda row: {
                **row,
                "agent_kind": body.agent_kind,
                "session_id": launched["session_id"],
                "session_tmux": launched.get("tmux_session"),
            },
        )
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
    return launched


@router.post("/workspaces/{studio_id}/dev/start")
async def start_workspace_dev(
    studio_id: str,
    request: Request,
    body: Optional[DevStartBody] = Body(default=None),
) -> Dict[str, Any]:
    """Sideload, consent, enable, acquire Dev Trust Lease, and start <300ms hot-reload watcher."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        mgr = dev_session.manager_for(request.app)
        return await mgr.start(studio_id, workspace, auto_approve=(body.auto_approve if body else True))
    except PluginStudioError as exc:
        raise _http_err(exc) from exc


@router.post("/workspaces/{studio_id}/dev/stop")
async def stop_workspace_dev(studio_id: str, request: Request) -> Dict[str, Any]:
    """Stop the Studio dev watcher and release the active Dev Trust Lease."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        mgr = dev_session.manager_for(request.app)
        return await mgr.stop(studio_id, workspace)
    except PluginStudioError as exc:
        raise _http_err(exc) from exc


@router.get("/workspaces/{studio_id}/readiness")
async def get_workspace_readiness(
    studio_id: str,
    request: Request,
    run_tests: bool = Query(default=False),
) -> Dict[str, Any]:
    """Run readiness validation (checker, prepare_kind, Warez static gates) for a workspace."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        folder = store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        report = await readiness.check_readiness(folder, run_tests=run_tests)
        await asyncio.to_thread(
            store.update_workspace,
            state_dir,
            studio_id,
            lambda row: {**row, "last_readiness": report},
        )
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
    return report


@router.post("/workspaces/{studio_id}/readiness")
async def post_workspace_readiness(
    studio_id: str,
    request: Request,
    body: Optional[ReadinessBody] = Body(default=None),
) -> Dict[str, Any]:
    """Explicitly re-run full readiness checks (including unit + sandbox tests when requested)."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        folder = store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        report = await readiness.check_readiness(
            folder,
            handle=(body.handle or "") if body else "",
            run_tests=body.run_tests if body else True,
        )
        await asyncio.to_thread(
            store.update_workspace,
            state_dir,
            studio_id,
            lambda row: {**row, "last_readiness": report},
        )
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
    return report


@router.post("/workspaces/{studio_id}/test-sandbox")
async def post_workspace_test_sandbox(
    studio_id: str,
    request: Request,
    body: Optional[TestSandboxBody] = Body(default=None),
) -> Dict[str, Any]:
    """Run ``checker`` + unit tests + live OS sandbox smoke probe for the workspace."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        folder = store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        return await actions.test_in_sandbox(
            folder,
            unit_only=body.unit_only if body else False,
            smoke_only=body.smoke_only if body else False,
        )
    except PluginStudioError as exc:
        raise _http_err(exc) from exc


@router.post("/workspaces/{studio_id}/install")
async def post_workspace_install(
    studio_id: str,
    request: Request,
    body: Optional[InstallWorkspaceBody] = Body(default=None),
) -> Dict[str, Any]:
    """1-click install, consent, enable, and start/push the Studio plugin to ``pluginsStore``."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        folder = store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        return await actions.install_workspace(
            request.app,
            folder,
            activate_runtime=body.activate_runtime if body else True,
            auto_approve=body.auto_approve if body else True,
        )
    except PluginStudioError as exc:
        raise _http_err(exc) from exc


@router.post("/workspaces/{studio_id}/publish")
async def post_workspace_publish(
    studio_id: str,
    body: PublishWorkspaceBody,
    request: Request,
) -> Dict[str, Any]:
    """Preview (``dry_run=True``) or submit a workspace plugin to Warez via Slice 5 publish pipeline."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        publish_req = actions.build_publish_request(
            workspace,
            mode=body.mode,
            repo=body.repo,
            tag=body.tag,
            pointer=body.pointer,
            commit_sha=body.commit_sha,
            subdir=body.subdir,
            version=body.version,
            digest=body.digest,
            dry_run=body.dry_run,
            include_workspace_files=body.include_workspace_files,
        )
        if not body.dry_run and not publish_req.digest and publish_req.path:
            preview_req = publish_req.model_copy(update={"dry_run": True})
            preview_res = await catalog_publish_routes.owner_publish(request, preview_req)
            if not preview_res.get("can_send"):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "folder_refused", "detail": "this folder would be refused", "refusals": preview_res.get("refusals", [])},
                )
            publish_req = publish_req.model_copy(update={"digest": preview_res.get("digest")})
        result = await catalog_publish_routes.owner_publish(request, publish_req)
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
    return {
        "ok": True,
        "dry_run": body.dry_run,
        "preview": result if body.dry_run else None,
        "submission": None if body.dry_run else result,
    }


@router.post("/workspaces/{studio_id}/preview-render")
async def post_workspace_preview_render(
    studio_id: str,
    request: Request,
    body: Optional[PreviewRenderBody] = Body(default=None),
) -> Dict[str, Any]:
    """Render Declarative UI v2 document or mint sandboxed iframe view URL for Studio preview."""
    state_dir = _state_dir(request)
    try:
        workspace = await asyncio.to_thread(store.get_workspace, state_dir, studio_id)
        store.contained_workspace_folder(state_dir, str(workspace["folder"]))
        mgr = dev_session.manager_for(request.app)
        return await mgr.preview_render(
            studio_id,
            workspace,
            theme_id=body.theme_id if body else None,
            width=body.width if body else None,
            height=body.height if body else None,
            surface_id=body.surface_id if body else None,
        )
    except PluginStudioError as exc:
        raise _http_err(exc) from exc
