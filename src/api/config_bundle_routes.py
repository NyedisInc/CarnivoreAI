
from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from src.api.auth import require_auth
from src.api.preferences_routes import broadcast_changed
from src.config import settings
from src.core import config_writer, ui_preferences_store, version
from src.core.config_bundle import constants
from src.core.config_bundle.bundle import ConfigBundle, build_export
from src.core.config_bundle.importer import ImportRefused, Mode
from src.core.config_bundle.service import run_import

logger = structlog.get_logger()

router = APIRouter(tags=["config-bundle"])


class ConfigImportRequest(BaseModel):
    """An import: the bundle file's content, how to apply it, and whether to only preview.

    Attributes:
      bundle (dict): the parsed bundle file, exactly as exported.
      mode (str): ``merge`` (default) or ``replace``.
      dry_run (bool): true (default) previews and writes nothing.
      confirm_launch_profiles_sha256 (str | None): the digest the preview's ``launch_profiles.sha256`` showed;
        required to apply a bundle that carries launch profiles (they can run shell).
      confirm_agents_sha256 (str | None): the digest the preview's ``agents.sha256`` showed; required to
        apply a bundle that writes agent wrapper commands (``script``, ``entry``, ``args``, ``env``; #2557).
      confirm_workspace_sha256 (str | None): the digest the preview's ``workspace.sha256`` showed; required to
        apply a bundle that writes new or changed ``workspace.env`` keys, ``default_shell`` or ``default_editor``.
      confirm_browser_sha256, confirm_provider_accounts_sha256, confirm_common_slash_commands_sha256,
        confirm_template_path_sha256 (str | None): the same for ``browser.executable``, an account's agent config
        folders, quick slash commands and ``template_path``; each preview block names its own ``sha256``.
    """

    model_config = ConfigDict(extra="forbid")

    bundle: Dict[str, Any]
    mode: Mode = "merge"
    dry_run: bool = True
    confirm_launch_profiles_sha256: Optional[str] = None
    confirm_agents_sha256: Optional[str] = None
    confirm_workspace_sha256: Optional[str] = None
    confirm_browser_sha256: Optional[str] = None
    confirm_provider_accounts_sha256: Optional[str] = None
    confirm_common_slash_commands_sha256: Optional[str] = None
    confirm_template_path_sha256: Optional[str] = None


def _config_path() -> Path:
    return Path(settings.auth_config_file).expanduser()


def _themes(request: Request) -> Any:
    services = getattr(request.app.state, "services", None)
    return getattr(services, "themes", None)


def _pins(themes: Any) -> Dict[str, str]:
    return dict(themes.pinned_themes) if themes is not None else {}


def _read_config() -> Dict[str, Any]:
    try:
        return config_writer.read_config(_config_path())
    except (FileNotFoundError, ValueError) as exc:
        logger.error("config_bundle_config_unreadable", error=str(exc))
        raise HTTPException(status_code=500, detail="configuration is missing or unreadable")


@router.get("/config/export", dependencies=[Depends(require_auth)])
async def export_config(request: Request) -> JSONResponse:
    """Download this install's configuration as one bundle file.

    Inputs: request (Request). Output: the bundle JSON with an attachment
      filename; ``redacted`` lists what was removed, by path.
    Raises: HTTPException 500 when config.json cannot be read.
    Example: GET /api/v1/config/export
    """
    body = build_export(
        _read_config(),
        _pins(_themes(request)),
        app_version=version.resolve_version(),
        host=socket.gethostname(),
    )
    stamp = body["exported_at"][:10].replace("-", "")
    return JSONResponse(
        body,
        headers={"Content-Disposition": f'attachment; filename="carnivore-config-{stamp}.json"'},
    )


@router.post("/config/import", dependencies=[Depends(require_auth)])
async def import_config(request: Request, body: ConfigImportRequest) -> Dict[str, Any]:
    """Preview (``dry_run``) or apply a config bundle.

    Inputs: request (Request); body (ConfigImportRequest).
    Output: ``{"status": "preview"|"applied"|"unchanged", "changes": [...],
      "counts", "truncated", "source", "stripped", "ignored", "backup"}``; a preview adds
      ``contains_commands`` and, when commands would be written, ``agents``, ``workspace``, ``browser``, ``provider_accounts``,
      ``common_slash_commands``, ``template_path`` and ``launch_profiles``
      blocks with the digest a real import must echo.
    Raises: HTTPException 413 (too large), 422 (not a valid bundle, or a
      section fails validation; the detail names fields, never values), 409
      (commands written without their confirmed digest), 500.
    Example: POST {"bundle": {...}, "mode": "merge", "dry_run": true}
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > constants.MAX_BUNDLE_BYTES:
        raise HTTPException(status_code=413, detail="that file is too large to be a config bundle")
    try:
        bundle = ConfigBundle.model_validate(body.bundle)
    except ValidationError as exc:
        lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:20]]
        raise HTTPException(status_code=422, detail=lines)

    themes = _themes(request)
    try:
        payload, built = run_import(
            _config_path(),
            bundle,
            mode=body.mode,
            dry_run=body.dry_run,
            pins=_pins(themes),
            themes=themes,
            host=socket.gethostname(),
            confirm_launch_profiles_sha256=body.confirm_launch_profiles_sha256,
            confirm_agents_sha256=body.confirm_agents_sha256,
            confirm_workspace_sha256=body.confirm_workspace_sha256,
            confirm_browser_sha256=body.confirm_browser_sha256,
            confirm_provider_accounts_sha256=body.confirm_provider_accounts_sha256,
            confirm_common_slash_commands_sha256=body.confirm_common_slash_commands_sha256,
            confirm_template_path_sha256=body.confirm_template_path_sha256,
        )
    except ImportRefused as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("config_bundle_import_config_unreadable", error=str(exc))
        raise HTTPException(status_code=500, detail="configuration is missing or unreadable")

    if built is not None:
        await broadcast_changed(
            request,
            ui_preferences_store.UpdateResult(
                ui_preferences_store.COMMITTED, built.revision, built.values, built.moved
            ),
            None,
        )
    return payload
