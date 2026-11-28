
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote, urlsplit

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
    agy_base: str = ""
    claude_base: str = ""
    codex_base: str = ""
    codex_chatgpt_base: str = ""
    copilot_base: str = ""


class MintFailed(RuntimeError):

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def _first_text(body: Any, names: tuple) -> str:
    return next((str(body[n]) for n in names if isinstance(body, dict) and isinstance(body.get(n), str) and body[n]), "")


def registered_agent_id(body: Any) -> str:
    nested = body.get("session") if isinstance(body, dict) else None
    return _first_text(nested, ("agent_id",)) or _first_text(body, ("agent_id", "id"))


def _epoch(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 else 0.0
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def routed_tool_base(body: Any, gateway_url: str, tool: str) -> str:
    profile = body.get("launch_profile") if isinstance(body, dict) else None
    tools = profile.get("tools") if isinstance(profile, dict) else None
    entry = tools.get(tool) if isinstance(tools, dict) else None
    raw = _first_text(entry, ("base_url",)).strip()
    try:
        got, gw = urlsplit(raw), urlsplit(gateway_url)
        same = got.scheme == "https" and bool(got.hostname) and got.hostname.lower() == (gw.hostname or "").lower() and (got.port or 443) == (gw.port or 443)
        clean = not (got.username or got.password or got.query or got.fragment) and not any(c.isspace() or c in "\\\"'`$" for c in raw)
    except ValueError:
        return ""
    return raw.rstrip("/") if same and clean else ""


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
        agent_id = registered_agent_id(registered.body)
        if not agent_id:
            raise MintFailed("argent did not name an agent")
        minted = await client.post("/v1/my/agent-sessions", json={"agent_id": agent_id, "session_uuid": session_ref})
    except ArgentError as exc:
        raise MintFailed(f"argent refused the mint ({exc.status or 'no answer'})", exc.code) from None
    key = _first_text(minted.body, ("plaintext_key", "key", "api_key"))
    if not key or any(c in key for c in "\r\n\x00"):
        raise MintFailed("argent returned no usable key")
    minted_key = MintedKey(key)
    minted_key.key_id = _first_text(minted.body, ("id", "session_id"))
    minted_key.claude_base = routed_tool_base(minted.body, cfg.gateway_url, "claude-code") if tool_kind == "claude" else ""
    minted_key.codex_base = routed_tool_base(minted.body, cfg.gateway_url, "codex") if tool_kind == "codex" else ""
    minted_key.codex_chatgpt_base = routed_tool_base(minted.body, cfg.gateway_url, "codex-chatgpt") if tool_kind == "codex" else ""
    minted_key.copilot_base = routed_tool_base(minted.body, cfg.gateway_url, "copilot-cli") if tool_kind == "copilot" else ""
    minted_key.agy_base = routed_tool_base(minted.body, cfg.gateway_url, "agy") if tool_kind == "agy" else ""
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
