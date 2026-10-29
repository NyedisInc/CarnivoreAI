
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StrictBool

from src.api.auth import require_auth
from src.api.mcp_admin_routes import _refuse_link
from src.config import settings
from src.config.mcp import MCP_KEY
from src.core import config_writer
from src.core.db import DatastoreError
from src.core.mcp import agent_tool_switches, aliases, tool_families, tool_groups, tool_switches, tools
from src.core.mcp_usage import rollup, view
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(prefix="/mcp-admin", tags=["mcp-admin"], dependencies=[Depends(_refuse_link), Depends(require_auth)])

MAX_CHANGES = 1000


class ToolSwitchesBody(BaseModel):
    """``PUT /mcp-admin/tools``: ``set`` maps a tool name to true (on) or false (off); a tool left out is not changed."""

    set: dict[str, StrictBool] = Field(min_length=1, max_length=MAX_CHANGES)


def _first_sentence(text: str) -> str:
    head = text.split(". ", 1)[0].strip()
    return head if head.endswith(".") else head + "."


def _usage(reset_now: bool = False) -> Optional[dict]:
    names = tools.tool_names()
    try:
        rollup.run()
        if reset_now:
            view.reset(names)
        return view.counts(names)
    except (sqlite3.Error, DatastoreError, OSError, RuntimeError) as exc:
        logger.warning("mcp_tool_usage_unreadable", error_type=type(exc).__name__, error=str(exc))
        return None


def tools_answer(usage: Optional[dict] = None) -> dict:
    chosen = tool_switches.overrides()
    family = agent_tool_switches.current()
    registered = {d["name"]: d for d in tools.tool_definitions()}
    seats = tool_groups.placement(registered)
    retired = aliases.table()
    by_group: dict[str, list[dict]] = {}
    for name in sorted(registered, key=lambda n: (seats[n].sub != tool_groups.DIRECT, seats[n].sub, n)):
        fam = tool_families.family_of(name)
        by_group.setdefault(seats[name].heading, []).append({
            "sub": seats[name].sub, "family": fam.label if fam is not None else "",
            "alias_of": retired.get(name, ""),
            "name": name, "description": _first_sentence(registered[name]["description"]),
            "write": tools.is_write(name), "enabled": tool_switches.is_on(name, chosen),
            "default_enabled": name not in tool_switches.DEFAULT_OFF,
            "family_hidden": bool(fam is not None and not family.shows(fam.key)),
            "hidden_because": fam.why if fam is not None and not family.shows(fam.key) else "",
        })
    seen = (usage or {}).get("tools", {})
    for rows in by_group.values():
        for row in rows:
            row["calls"] = seen.get(row["name"], {}).get("calls") if usage else None
            row["daily"] = seen.get(row["name"], {}).get("daily") if usage else None
    ordered = sorted(by_group, key=tool_groups.heading_order)
    return {"groups": [{"group": g, "tools": by_group[g]} for g in ordered],
            "usage": None if usage is None else {"since": usage["since"], "days": usage["days"]}}


@router.get("/tools")
async def get_tools() -> dict:
    """Every registered tool by group with its on/off state (#1824). Output: see :func:`tools_answer`."""
    return tools_answer(await run_in_threadpool(_usage))


@router.post("/tools/usage/reset")
async def reset_tool_usage() -> dict:
    """Zero the dev tab's call counts as of now; owner only (#1824).

    Description: records the reset moment and today's count per tool in the usage store's ``view_reset`` table. No count
      is deleted or edited, so the retired-name evidence (#1711) and ``GET /mcp-usage`` are unchanged.
    Output: the same document as ``GET /mcp-admin/tools``, with ``usage.since`` now set.
    Raises: HTTPException 503 when the usage file cannot be read or written.
    """
    usage = await run_in_threadpool(_usage, True)
    if usage is None:
        raise HTTPException(status_code=503, detail="the usage counts could not be reset")
    return tools_answer(usage)


@router.put("/tools")
async def put_tools(body: ToolSwitchesBody) -> dict:
    """Switch tools on or off for every MCP caller on this computer; owner only, live, no restart.

    Description: written to ``mcp.tool_overrides`` through ``config_writer``; a change equal to the tool's default removes
      its entry. The tool list and the MCP fingerprint read it on every request, so connected sessions refresh.
    Inputs: body (ToolSwitchesBody). Output: the same document as ``GET`` after the change.
    Raises: HTTPException 422 for an unknown tool or switching an always-on tool off; 500 when config.json is unwritable.
    Example: PUT {"set": {"session_pin": false}}
    """
    registered = frozenset(tools.tool_names())
    try:
        tool_switches.merged(body.set, registered, {})
    except tool_switches.ToolSwitchError as exc:
        raise api_error(422, "invalid_request", exc, step="put_tools") from exc

    def mutate(doc: dict) -> dict:
        block = doc.get(MCP_KEY)
        block = dict(block) if isinstance(block, dict) else {}
        current = block.get("tool_overrides")
        block["tool_overrides"] = tool_switches.merged(body.set, registered, current if isinstance(current, dict) else {})
        return {**doc, MCP_KEY: block}

    try:
        await asyncio.to_thread(config_writer.commit, Path(settings.auth_config_file).expanduser(), mutate)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.error("mcp_tool_switches_unwritable", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="config.json could not be updated") from exc
    settings.drop_auth_config_cache()
    logger.info("mcp_tool_switches_set", changed=sorted(body.set))
    return tools_answer(await run_in_threadpool(_usage))
