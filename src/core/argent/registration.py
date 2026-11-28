
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.config import settings as app_settings
from src.core.argent import fallback_spend, row_state
from src.core.argent import session_ref as refs
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, NotFound
from src.core.argent.mint import registered_agent_id
from src.core.argent.runtime import get_runtime
from src.core.hosts.machine_identity import computer_display_name
from src.core.launch_profiles.resolve import custom_tool
from src.core.launch_profiles.store import LaunchProfileStore
from src.core.sessions.session_events import ENDED, RENAMED, STARTED, SessionEvent

logger = structlog.get_logger()

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
TOOL_KINDS = ("claude", "codex", "copilot", "agy")


def tool_kind(agent_family: str, agent_type: str = "") -> str:
    family = (agent_family or "").strip().lower()
    if family == "custom" and agent_type:
        profiles = LaunchProfileStore(Path(app_settings.auth_config_file).expanduser()).list()
        found = next((custom_tool(p) for p in profiles if p.id == agent_type), "")
        if found:
            return found
    return family if family in TOOL_KINDS else "other"


def _clip(text: str, limit: int) -> str:
    return _CONTROL.sub(" ", str(text or "")).strip()[:limit]


def payload(event: SessionEvent, ref: str, computer: str) -> Dict[str, str]:
    return {"session_uuid": ref, "display_name": _clip(event.display_name or event.tmux_name, 120) or ref, "project": _clip(event.project, 120),
            "tool_kind": tool_kind(event.agent_family, event.agent_type), "computer": _clip(computer, 80)}


def _login() -> Optional[Dict[str, Any]]:
    runtime = get_runtime()
    login = runtime.store.get_login()
    token = runtime.tokens.read(str(login["tenant_id"])) if login else None
    cfg = settings_module.read()
    return {"tenant": str(login["tenant_id"]), "token": token, "url": cfg.server_url} if login and token and cfg.server_url else None


async def follow_rename(event: SessionEvent) -> None:
    if event.kind != RENAMED:
        return
    try:
        await asyncio.to_thread(refs.rename_all, event.old_name, event.tmux_name)
    except Exception as exc:
        logger.warning("gateway_rename_follow_failed", error_type=type(exc).__name__)


class Registrar:

    def __init__(self, transport: Optional[Any] = None) -> None:
        self._transport = transport

    async def __call__(self, event: SessionEvent) -> None:
        try:
            auth = await asyncio.to_thread(_login)
            if auth is None:
                return
            if event.kind == STARTED:
                await self._register(event, auth)
            elif event.kind == ENDED:
                await self._deregister(event, auth)
        except (ArgentError, OSError) as exc:
            logger.warning("argent_registration_failed", kind=event.kind, error_type=type(exc).__name__)
        except Exception as exc:
            logger.warning("argent_registration_error", kind=event.kind, error_type=type(exc).__name__)

    def _client(self, auth: Dict[str, Any]) -> ArgentClient:
        return ArgentClient(auth["url"], lambda: auth["token"], transport=self._transport)

    async def _register(self, event: SessionEvent, auth: Dict[str, Any]) -> None:
        computer = await asyncio.to_thread(computer_display_name)
        ref = await asyncio.to_thread(refs.ref_for_name, auth["tenant"], event.tmux_name)
        body = await asyncio.to_thread(payload, event, ref, computer)
        reply = await self._client(auth).post("/v1/my/carnivore-sessions/register", json=body)
        await asyncio.to_thread(refs.bind, auth["tenant"], event.tmux_name, session_uuid=event.session_uuid or "",
                                agent_id=registered_agent_id(reply.body), reg=body)

    async def _deregister(self, event: SessionEvent, auth: Dict[str, Any]) -> None:
        ref = await asyncio.to_thread(refs.ref_for_name, auth["tenant"], event.tmux_name)
        await fallback_spend.flush_ended(auth["tenant"], event.tmux_name, self._client(auth))
        try:
            await self._client(auth).post("/v1/my/carnivore-sessions/deregister", json={"session_uuid": ref})
        except NotFound:
            pass
        finally:
            if event.reason in refs.RETIRING_REASONS:
                await asyncio.to_thread(refs.retire, auth["tenant"], event.tmux_name)
        await asyncio.to_thread(row_state.drop_keys, auth["tenant"], ref)
