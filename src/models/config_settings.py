
from typing import Optional, Dict
from pydantic import BaseModel, Field




class WorkspaceUpdate(BaseModel):
    """PATCH body sub-block for ``AuthConfig.workspace``.

    "Leave unchanged" is omission, as everywhere else on this endpoint;
    an explicit empty string clears a field back to "not configured",
    which is a meaningful state here (an unset development root means the
    app behaves exactly as it did before the setting existed).

    ``env`` is the exception to the omit/merge rule: it is sent WHOLE or
    not at all, because a key-wise merge has no way to express deleting a
    row. Values are validated in ``src/core/workspace_settings.py`` at
    the route boundary and are never logged.
    """

    model_config = {"extra": "forbid"}

    development_root: Optional[str] = None
    default_shell: Optional[str] = None
    default_editor: Optional[str] = None
    env: Optional[Dict[str, str]] = None


class ServerPrefsUpdate(BaseModel):
    """PATCH body sub-block for ``AuthConfig.server_prefs``.

    Writing ``bind_host`` records a PREFERENCE. It cannot widen an
    instance's exposure: the address actually bound is resolved once by
    ``src/core/setup_state.resolve_exposure``, downstream of this value,
    and that function pins loopback until setup is complete. Nor does it
    move a live socket - uvicorn binds once, so the change applies on the
    next restart and the UI must say so.
    """

    model_config = {"extra": "forbid"}

    bind_host: Optional[str] = None
    tls_preferred: Optional[bool] = None
    developer_mode: Optional[bool] = None


class ConfigSettingsUpdateRequest(BaseModel):
    """Request body for ``PATCH /api/v1/config/settings``.

    Top-level keys are the writable blocks the settings screen exposes
    (``workspace`` and ``server_prefs``; notification settings have their own route,
    ``notification_settings_routes.py``) - HOST/server bind is
    deliberately absent: it lives in ``.env``, not ``config.json``, has
    no atomic-write convention in this codebase, and a bad value can
    strand the server (the launchd wrapper refuses to boot on a
    wildcard bind). The settings screen shows HOST read-only instead of
    exposing it here. ``extra="forbid"`` rejects any other top-level key
    outright rather than silently ignoring it.
    """
    model_config = {"extra": "forbid"}

    workspace: Optional[WorkspaceUpdate] = None
    server_prefs: Optional[ServerPrefsUpdate] = None
