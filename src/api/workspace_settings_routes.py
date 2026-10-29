
import structlog
from fastapi import APIRouter, Depends, HTTPException
from src.config import settings
from src.core.workspace_settings import (
    WorkspaceValidationError,
    validate_bind_host,
    validate_development_root,
    validate_editor,
    validate_env_map,
    validate_shell,
)
from src.models import ConfigSettingsUpdateRequest

from src.api.auth import require_auth
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter()



@router.get("/config/settings", dependencies=[Depends(require_auth)])
async def get_settings():
    """
    Get the settings-screen payload: the launch wrappers and family
    registry and the server bind address
    (read-only - see ``Settings.get_settings_summary``).

    Returns:
        dict with keys ``agents``, ``server``.

    Raises:
        HTTPException: 500 if config.json is missing or unreadable.
    """
    try:
        return settings.get_settings_summary()
    except FileNotFoundError as e:
        logger.error("settings_summary_config_missing", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Configuration not found. Run setup_auth.py first."
        )
    except Exception as e:
        raise api_error(500, "settings_read_failed", None, error_type=type(e).__name__) from e


@router.patch("/config/settings", dependencies=[Depends(require_auth)])
async def update_settings(body: ConfigSettingsUpdateRequest):
    """
    Apply a partial update to the ``workspace`` and
    ``server_prefs`` blocks of config.json. A body carrying ``agents`` is
    a 422: launch commands are wrappers now (see the module docstring).

    Only the fields the client actually SET are written (Pydantic's
    ``model_fields_set``, not "is not None") - this is what makes
    omitting a secret field mean "leave unchanged" while still allowing
    an explicit empty-string write to clear it. Unknown top-level or
    nested keys are already rejected by ``ConfigSettingsUpdateRequest``'s
    ``extra="forbid"`` before this handler runs (FastAPI returns 422).

    Args:
        body: partial settings update. Every block is optional; a
            request with none is a harmless no-op that returns the
            unchanged summary.

    Returns:
        The full post-write settings summary (same shape as GET).

    Raises:
        HTTPException: 400 on a value that fails validation, 500 on a
            config.json I/O or JSON error.
    """
    workspace_update: dict = {}
    env_warnings: list = []
    if body.workspace is not None:
        raw_workspace = body.workspace.model_dump(
            include=body.workspace.model_fields_set
        )
        try:
            if "development_root" in raw_workspace:
                workspace_update["development_root"] = validate_development_root(
                    raw_workspace["development_root"]
                )
            if "default_shell" in raw_workspace:
                workspace_update["default_shell"] = validate_shell(
                    raw_workspace["default_shell"]
                )
            if "default_editor" in raw_workspace:
                workspace_update["default_editor"] = validate_editor(
                    raw_workspace["default_editor"]
                )
            if "env" in raw_workspace:
                env_map, env_warnings = validate_env_map(raw_workspace["env"])
                workspace_update["env"] = env_map
        except WorkspaceValidationError as e:
            logger.info("workspace_settings_rejected", reason=str(e))
            raise api_error(400, "settings_invalid", e, step="update_settings") from e

    server_prefs_update: dict = {}
    if body.server_prefs is not None:
        raw_prefs = body.server_prefs.model_dump(
            include=body.server_prefs.model_fields_set
        )
        try:
            if "bind_host" in raw_prefs:
                server_prefs_update["bind_host"] = validate_bind_host(
                    raw_prefs["bind_host"]
                )
            if "tls_preferred" in raw_prefs:
                server_prefs_update["tls_preferred"] = bool(
                    raw_prefs["tls_preferred"]
                )
            if "developer_mode" in raw_prefs:
                server_prefs_update["developer_mode"] = bool(
                    raw_prefs["developer_mode"]
                )
        except WorkspaceValidationError as e:
            logger.info("server_prefs_rejected", reason=str(e))
            raise api_error(400, "settings_invalid", e, step="update_settings") from e

    logger.info(
        "settings_update_requested",
        workspace_fields=sorted(workspace_update.keys()),
        workspace_env_names=sorted((workspace_update.get("env") or {}).keys()),
        server_prefs_fields=sorted(server_prefs_update.keys()),
    )

    try:
        summary = settings.update_settings_config(
            workspace_update=workspace_update or None,
            server_prefs_update=server_prefs_update or None,
        )
        summary["workspace_warnings"] = env_warnings
        return summary
    except FileNotFoundError as e:
        logger.error("settings_update_config_missing", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Configuration not found. Run setup_auth.py first."
        )
    except ValueError as e:
        logger.warning("settings_update_validation_error", error=str(e))
        raise api_error(400, "settings_invalid", e, step="update_settings") from e
    except Exception as e:
        raise api_error(500, "settings_write_failed", None, error_type=type(e).__name__) from e
