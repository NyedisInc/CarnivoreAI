"""Per-session terminal settings a blueprint member remembers (issue #1323).

A member saved from a live session carries the settings the user set on THAT
session: keep awake (the coffee cup), muted notifications and the terminal
background override. Launching a member that has to be CREATED applies them
through the very routes the UI toggles call, so there is no second
implementation; a member that is already running is reused untouched.

Only a setting that is ON (or an override that exists) is captured, so a
blueprint of default sessions stays as small as before. Excluded on purpose:
per-device or per-window state (scroll, active tab, the size crown), identity
(names, ids, pins, groups), content (notes) and an uploaded background picture
(a file, not a setting).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Set

import structlog
from fastapi import HTTPException, Request

from src.config import settings
from src.core.auto_sleep import store as auto_sleep_store
from src.models.auto_sleep import KeepAwakeWrite
from src.models.blueprints import BlueprintSession
from src.models.notifications import MuteNotificationsRequest
from src.models.themes import UpdateSessionBackgroundRequest

logger = structlog.get_logger()


class CaptureSources:

    def __init__(self, themes: Any = None, keep_awake: Optional[Set[str]] = None,
                 backgrounds: Any = None) -> None:
        self.themes = themes
        self.keep_awake = keep_awake or set()
        self.backgrounds = backgrounds

    @classmethod
    async def read(cls, request: Request) -> "CaptureSources":
        keep: Set[str] = set()
        try:
            config = await asyncio.to_thread(auto_sleep_store.read, Path(settings.auth_config_file).expanduser())
            keep = set(config.keep_awake)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("blueprint_capture_keep_awake_unread", error=type(exc).__name__)
        return cls(themes=request.app.state.services.themes, keep_awake=keep,
                   backgrounds=getattr(request.app.state, "session_background_store", None))

    def member_fields(self, row: Any, session_uuid: str) -> Dict[str, Any]:
        tmux = row["tmux_name"]
        out: Dict[str, Any] = {
            "theme": self.themes.resolve_project_theme(row["working_dir"], tmux) if self.themes else None,
            "keep_awake": True if session_uuid in self.keep_awake else None,
            "notifications_muted": True if row["notifications_muted"] else None,
        }
        entry = self.backgrounds.get(tmux) if self.backgrounds is not None and tmux else None
        if entry:
            out["background"] = {"theme_id": entry.get("theme_id"), "dim": entry.get("dim"),
                                 "disabled": bool(entry.get("disabled"))}
        return out


async def apply_settings(request: Request, member: BlueprintSession, session_uuid: Optional[str],
                         tmux_name: Optional[str]) -> None:
    """Apply a newly created member's saved settings through the UI's own routes.

    Description: the session is already running, so a setting that cannot be applied is logged and
      skipped; it never fails the member.
    """
    from src.api.auto_sleep_routes import put_keep_awake
    from src.api.session_background_routes import set_session_background
    from src.api.session_records_routes import set_session_notification_policy

    steps = []
    if member.keep_awake and session_uuid:
        steps.append(("keep_awake", put_keep_awake(
            KeepAwakeWrite(session_uuid=session_uuid, keep_awake=True), request)))
    if member.notifications_muted and session_uuid:
        steps.append(("notifications_muted", set_session_notification_policy(
            request, session_uuid, MuteNotificationsRequest(muted=True))))
    if member.background is not None and tmux_name:
        steps.append(("background", set_session_background(
            request, tmux_name, UpdateSessionBackgroundRequest(
                theme_id=member.background.theme_id, dim=member.background.dim,
                disabled=member.background.disabled))))
    for name, call in steps:
        try:
            await call
        except HTTPException as exc:
            logger.warning("blueprint_setting_not_applied", setting=name, status=exc.status_code)
