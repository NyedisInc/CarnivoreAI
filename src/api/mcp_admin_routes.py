
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StrictBool, StrictInt

from src.api.auth import require_auth
from src.api.catalog_required_routes import run_required_pass
from src.config import mcp_launch, settings
from src.core import config_writer
from src.core.mcp import channel as channel_events
from src.core.mcp import agent_tool_switches, instructions, pending, token_store, tools, trusted_proxy
from src.core.mcp.write_tools import gate_enabled

logger = structlog.get_logger()


def _refuse_link(request: Request) -> None:
    if request.scope.get("via_link"):
        raise HTTPException(status_code=403, detail="not available over the link")


router = APIRouter(prefix="/mcp-admin", tags=["mcp-admin"], dependencies=[Depends(_refuse_link), Depends(require_auth)])


class EnabledBody(BaseModel):
    """``mcp.enabled``: False makes ``POST /mcp`` answer 404."""

    enabled: bool


class AgentToolsBody(BaseModel):
    """``PUT /mcp-admin/agent-tools`` (#1685, #1754): any of the three checkboxes; a field left out is not changed."""

    huddle: Optional[StrictBool] = None
    swarm: Optional[StrictBool] = None
    app_settings: Optional[StrictBool] = None


class TrustedProxiesBody(BaseModel):
    """``PUT /mcp-admin/trusted-proxies`` (#1741): the whole list of trusted proxy addresses; empty turns it off."""

    hosts: list[str]


class MintBody(BaseModel):
    """A token to mint: its name, scope and optional expiry in days."""

    name: str
    scope: Literal["read", "write"]
    expires_in_days: Optional[StrictInt] = None


def _enabled() -> bool:
    try:
        return bool(settings.load_auth_config().mcp.enabled)
    except (ValueError, OSError):
        return False


@router.get("")
async def mcp_status() -> dict:
    """What the panel shows: switch, endpoint, gate, the real tool registry and the guide clients receive.

    Output: {enabled, endpoint, gate_cross_session_actions, channels, channel_streams (open channel streams now),
      agent_huddle_tools, agent_swarm_tools (#1685), agent_app_settings_tools (#1754), hidden_families (the tool
      families agents are not offered now: [{family, why, how_to_enable}]), trusted_proxy_hosts (#1741),
      tools: [{name, description, write}], guide}.
    """
    switches = agent_tool_switches.current()
    return {
        "enabled": _enabled(),
        "endpoint": mcp_launch.mcp_url(settings.port),
        "gate_cross_session_actions": gate_enabled(),
        "channels": channel_events.channels_enabled(),
        "channel_streams": channel_events.REGISTRY.count(),
        "agent_huddle_tools": switches.huddle,
        "agent_swarm_tools": switches.swarm,
        "agent_app_settings_tools": switches.app_settings,
        "hidden_families": agent_tool_switches.hidden_family_rows(switches),
        "trusted_proxy_hosts": trusted_proxy.configured(),
        "tools": [{"name": d["name"], "description": d["description"], "write": tools.is_write(d["name"])}
                  for d in tools.tool_definitions()],
        "guide": instructions.guide(),
    }


async def _write_mcp_fields(fields: dict[str, Any], event: str) -> None:
    def mutate(doc: dict) -> dict:
        block = doc.get("mcp")
        block = dict(block) if isinstance(block, dict) else {}
        block.update(fields)
        return {**doc, "mcp": block}

    try:
        await asyncio.to_thread(config_writer.commit, Path(settings.auth_config_file).expanduser(), mutate)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.error(f"mcp_{event}_unwritable", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="config.json could not be updated") from exc
    settings.drop_auth_config_cache()
    logger.info(f"mcp_{event}_set", **fields)


async def _write_mcp_flag(field: str, value: bool, event: str) -> dict:
    await _write_mcp_fields({field: value}, event)
    return {"enabled": value}


def _agent_tools_answer() -> dict:
    switches = agent_tool_switches.current()
    return {"huddle": switches.huddle, "swarm": switches.swarm, "app_settings": switches.app_settings}


@router.get("/agent-tools")
async def get_agent_tools() -> dict:
    """The per-computer checkboxes for the agent tool families (#1685, #1754): Task Manager off, swarm on, app settings off by default.
    """
    return _agent_tools_answer()


@router.put("/agent-tools")
async def put_agent_tools(body: AgentToolsBody, request: Request) -> dict:
    fields = {k: v for k, v in ((agent_tool_switches.TASK_MANAGER_FIELD, body.huddle),
                                (agent_tool_switches.SWARM_FIELD, body.swarm),
                                (agent_tool_switches.APP_SETTINGS_FIELD, body.app_settings)) if v is not None}
    if not fields:
        raise HTTPException(status_code=422, detail="give huddle, swarm, app_settings or any of them")
    await _write_mcp_fields(fields, "agent_tools")
    if agent_tool_switches.TASK_MANAGER_FIELD in fields:
        await run_required_pass(request.app)
    return _agent_tools_answer()


@router.put("/trusted-proxies")
async def put_trusted_proxies(body: TrustedProxiesBody) -> dict:
    """Set the reverse proxies whose calls may reach ``/mcp`` with an owner-minted token (#1741); owner only.

    Description: each entry must be an exact IP address (no CIDR, no hostname) that is not loopback, unspecified
      or multicast; entries are stored canonical and de-duplicated in ``mcp.trusted_proxy_hosts`` through
      ``config_writer``. An empty list restores the loopback-only gate. Read live by ``require_agent``.
    Inputs: body (TrustedProxiesBody). Output: {hosts: list[str]} - what was stored.
    Raises: HTTPException 422 for a bad entry; 500 when config.json is unwritable.
    """
    try:
        hosts = trusted_proxy.validate_list(body.hosts)
    except trusted_proxy.TrustedProxyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _write_mcp_fields({trusted_proxy.FIELD: hosts}, "trusted_proxies")
    return {"hosts": hosts}


@router.put("/settings")
async def put_enabled(body: EnabledBody) -> dict:
    """Turn the MCP endpoint on or off (new and restarted sessions pick the change up).

    Inputs: body (EnabledBody). Output: {enabled}. Raises: HTTPException 500 when config.json is unwritable.
    """
    return await _write_mcp_flag("enabled", body.enabled, "enabled")


@router.put("/agent-notify")
async def put_agent_notify(body: EnabledBody) -> dict:
    """Turn agent notify (the ``notify`` tool and its route) on or off; owner only, never synced.

    Inputs: body (EnabledBody). Output: {enabled}. Raises: HTTPException 500 when config.json is unwritable.
    """
    return await _write_mcp_flag("agent_notify", body.enabled, "agent_notify")


@router.put("/channels")
async def put_channels(body: EnabledBody) -> dict:
    """Turn channel delivery (``mcp.channels``, research preview) on or off; owner only, default off.
    """
    return await _write_mcp_flag("channels", body.enabled, "channels")


def _migrator(request: Request) -> Any:
    migrator = getattr(request.app.state, "mcp_bridge_migrator", None)
    if migrator is None:
        raise HTTPException(status_code=503, detail="the bridge migration is not running yet")
    return migrator


@router.get("/bridge-migration")
async def bridge_migration_status(request: Request) -> dict:
    """Which sessions still ride the carnivore MCP over plain HTTP and what the migration did with each (#1672).

    Description: ``src/core/mcp_bridge/migration/``. Each session ever measured on HTTP is listed with its state
      (``pending`` and why it waits, ``restarted`` awaiting verification, ``migrated``, ``skipped`` with no
      resumable conversation, ``gave_up`` after the attempt cap), attempts and last outcome.
    Output: {enabled, bridge_ready, looping, last_pass, last_pass_at, sessions: [...]}.
    """
    return _migrator(request).status()


@router.post("/bridge-migration/run")
async def bridge_migration_run(request: Request) -> dict:
    """Run one migration pass now: at most one idle HTTP session is resumed onto the bridge, never a busy one.

    Output: the status, as ``GET /mcp-admin/bridge-migration``, after the pass.
    """
    return await _migrator(request).run_pass()


@router.put("/bridge-migration")
async def put_bridge_migration(body: EnabledBody) -> dict:
    """Turn the automatic bridge migration (``mcp.bridge_migration``, default on) on or off; owner only.

    Inputs: body (EnabledBody). Output: {enabled}. Raises: HTTPException 500 when config.json is unwritable.
    """
    return await _write_mcp_flag("bridge_migration", body.enabled, "bridge_migration")


@router.get("/tokens")
async def list_tokens() -> dict:
    """Every minted token (name, scope, created, last used, expiry; never a secret). Output: {tokens}."""
    return {"tokens": token_store.get_store().list()}


@router.post("/tokens", status_code=201)
async def mint_token(body: MintBody) -> dict:
    """Mint a token. Output: {token: row, secret} - the secret is shown here once and never stored.

    Raises: HTTPException 422 for a bad name, scope, expiry or a duplicate, 500 when the file cannot be written.
    """
    try:
        row, secret = await asyncio.to_thread(token_store.get_store().mint, body.name, body.scope, body.expires_in_days)
    except token_store.TokenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("mcp_token_unwritable", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="the token file could not be written") from exc
    return {"token": row, "secret": secret}


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str) -> dict:
    """Revoke a token; its next request is refused. Output: {revoked: id}. Raises: HTTPException 404 unknown."""
    try:
        found = await asyncio.to_thread(token_store.get_store().revoke, token_id)
    except token_store.TokenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="the token file could not be written") from exc
    if not found:
        raise HTTPException(status_code=404, detail="no such token")
    pending.get_store().deny_for_caller(f"mcp-token:{token_id}")
    return {"revoked": token_id}
