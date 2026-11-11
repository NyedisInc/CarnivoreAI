
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.notifications import doc_model
from src.core.notifications.cards import git_stats

logger = structlog.get_logger()

MAX_TURN_SECONDS = 24 * 3600
STATS_BUDGET_SECONDS = 10.0
THREAD_LINES = 3
THREAD_SCAN = 50


class LiveSources:

    def __init__(self, app_state: Any) -> None:
        self._state = app_state

    async def dialog(self, session_id: str) -> Optional[Dict[str, Any]]:
        inbox = getattr(self._state, "approvals_inbox", None)
        if inbox is None:
            return None
        return next((i for i in await inbox.list_items() if i.get("source") == "dialog" and i.get("session_id") == session_id), None)

    def details_on(self, dest_id: str) -> bool:
        from src.core.notifications.destinations.service import get_service  # noqa: PLC0415

        try:
            value = doc_model.effective_value(get_service(self._state).docs.snapshot(), doc_model.extra_path(dest_id, "details"), None)
        except (ValueError, KeyError, OSError):
            return True
        return True if value is None else bool(value)

    def _turn_minutes(self, session_id: str) -> Optional[int]:
        watcher = getattr(self._state, "attention_watcher", None)
        observation = watcher.observation_for(session_id) if watcher is not None else None
        facts = getattr(getattr(observation, "evidence", None), "transcript", None)
        began, ended = getattr(facts, "newest_user_prompt_at", None), getattr(facts, "turn_end_at", None)
        if began is None or ended is None or not 30 <= (ended - began).total_seconds() <= MAX_TURN_SECONDS:
            return None
        return max(1, round((ended - began).total_seconds() / 60))

    async def _signin_sessions(self, event: Any) -> Dict[str, Any]:
        from src.api import session_account_listing  # noqa: PLC0415

        account = (event.card_hint or {}).get("account_id")
        if not account:
            return {}
        try:
            manager = self._state.session_manager
            names = [manager._label_for_tmux_name(i.tmux_session) or i.tmux_session for i in await manager.list_session_infos()
                     if i.tmux_session and session_account_listing.cached_account(i) == account]
        except (AttributeError, OSError, ValueError) as exc:
            logger.debug("notify_card_signin_sessions_unreadable", error_type=type(exc).__name__)
            return {}
        return {"sessions": names[:6]} if names else {}

    async def _crosstalk_thread(self, session_id: str) -> Dict[str, Any]:
        try:
            records = list(self._state.session_manager._toast_inbox.bucket(session_id))
        except AttributeError as exc:
            logger.debug("notify_card_thread_unreadable", error_type=type(exc).__name__)
            return {}

        def pick() -> list:
            return [[t.session_label or t.session_name or "agent", t.body] for t in records[:THREAD_SCAN]
                    if t.notify_type == "agent.message" and t.body][:THREAD_LINES][::-1]

        thread = await asyncio.to_thread(pick)
        return {"thread": thread} if thread else {}

    async def extra(self, event: Any) -> Dict[str, Any]:
        if event.type_id == "provider.needs_login":
            return await self._signin_sessions(event)
        if event.type_id == "agent.message" and event.session_id:
            return await self._crosstalk_thread(event.session_id)
        if not event.session_id or event.type_id not in ("session.finished", "session.permission", "approval.agent_action"):
            return {}
        from src.api.session_git_routes import _session_directory, watch_for  # noqa: PLC0415

        try:
            manager = self._state.session_manager
            info = await manager.get_session_info(event.session_id)
            if event.type_id != "session.finished":
                folder = getattr(getattr(info, "session", None), "working_dir", None)
                return {"dir": str(folder).replace(os.path.expanduser("~"), "~", 1)} if folder else {}
            out: Dict[str, Any] = {}
            minutes = self._turn_minutes(event.session_id)
            if minutes:
                out["mins"] = minutes
            directory = await _session_directory(manager, info) if info is not None else None
            status = await watch_for(self._state).read(event.session_id, directory) if directory is not None else None
        except (AttributeError, OSError, ValueError) as exc:
            logger.debug("notify_card_git_unreadable", error_type=type(exc).__name__)
            return {}
        if status is None or status.state != "ok" or not status.files:
            return out
        out.update(files=[f.path for f in status.files[:3]], nfiles=len(status.files))
        try:
            stats = await asyncio.wait_for(asyncio.to_thread(
                git_stats.file_stats, Path(status.repo_root or directory), status.files, unborn=status.unborn), STATS_BUDGET_SECONDS)
        except (asyncio.TimeoutError, OSError, ValueError) as exc:
            logger.debug("notify_card_stats_unreadable", error_type=type(exc).__name__)
            return out
        if any(stats):
            out["stats"] = stats
        return out
