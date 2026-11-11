
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

import structlog

from src.core.argent import session_ref as refs
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, NotFound
from src.core.argent.runtime import get_runtime

logger = structlog.get_logger()

MINT_TIMEOUT_SECONDS = 6.0


class MintedKey(str):

    key_id: str = ""
    expires_at: float = 0.0


class MintFailed(RuntimeError):

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def _first_text(body: Any, names: tuple) -> str:
    return next((str(body[n]) for n in names if isinstance(body, dict) and isinstance(body.get(n), str) and body[n]), "")


def _epoch(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 else 0.0
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


async def mint_session_key(session_ref: str, display_name: str, tool_kind: str, *, transport: Optional[Any] = None) -> MintedKey:
    cfg = settings_module.read()
    login = get_runtime().store.get_login()
    token = get_runtime().tokens.read(str(login["tenant_id"])) if login else None
    if not cfg.server_url or not token:
        raise MintFailed("not logged in to argent")
    client = ArgentClient(cfg.server_url, lambda: token, transport=transport)
    try:
        known = await asyncio.to_thread(refs.registration, str(login["tenant_id"]), session_ref)
        registered = await client.post("/v1/my/carnivore-sessions/register", json={
            "session_uuid": session_ref, "display_name": (known.get("display_name") or display_name or session_ref)[:120], "project": known.get("project", ""),
            "tool_kind": tool_kind, "computer": known.get("computer", "")})
        agent_id = _first_text(registered.body, ("agent_id", "id"))
        if not agent_id:
            raise MintFailed("argent did not name an agent")
        minted = await client.post("/v1/my/agent-sessions", json={"agent_id": agent_id, "session_uuid": session_ref})
    except ArgentError as exc:
        raise MintFailed(f"argent refused the mint ({exc.status or 'no answer'})", exc.code) from None
    key = _first_text(minted.body, ("key", "api_key"))
    if not key or any(c in key for c in "\r\n\x00"):
        raise MintFailed("argent returned no usable key")
    minted_key = MintedKey(key)
    minted_key.key_id = _first_text(minted.body, ("id", "session_id"))
    minted_key.expires_at = _epoch(minted.body.get("expires_at") if isinstance(minted.body, dict) else None)
    return minted_key


async def revoke_key(key_id: str, *, transport: Optional[Any] = None) -> bool:
    cfg = settings_module.read()
    login = get_runtime().store.get_login()
    token = get_runtime().tokens.read(str(login["tenant_id"])) if login else None
    if not cfg.server_url or not token or not key_id:
        return False
    try:
        await ArgentClient(cfg.server_url, lambda: token, transport=transport).post(f"/v1/my/agent-sessions/{quote(key_id, safe='')}/revoke", json={})
    except NotFound:
        return True
    except ArgentError as exc:
        logger.warning("argent_key_revoke_failed", status=exc.status)
        return False
    return True
