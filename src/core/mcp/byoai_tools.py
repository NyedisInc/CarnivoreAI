
from __future__ import annotations

from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _via_route

MAX_CALLS = 100


def _clean(value: Any) -> Any:
    from src.core.mcp.tools import redact_text

    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return redact_text(value) if isinstance(value, str) else value


async def ai_connections_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import ai_routes

    return _ok(_clean(await _via_route(ai_routes.list_connections())))


async def ai_models_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.mcp import lean_answers

    from src.api import ai_routes

    connection_id = args.get("connection_id")
    if not isinstance(connection_id, str) or not connection_id:
        raise ToolError("connection_id is required")
    refresh = args.get("refresh", False)
    if type(refresh) is not bool:
        raise ToolError("refresh must be true or false")
    if refresh and caller.scope != "write":
        raise ToolError("refresh asks the provider and needs a write token")
    full = lean_answers.detail_flag(args)
    answer = _clean(await _via_route(ai_routes.connection_models(
        connection_id, refresh, cached_only=caller.scope != "write")))
    return _ok(answer if full else lean_answers.models(answer))


async def ai_features_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import ai_routes

    return _ok(_clean(await _via_route(ai_routes.list_features())))


async def ai_calls_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import ai_routes

    limit = args.get("limit", 20)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CALLS:
        raise ToolError(f"limit must be an integer from 1 to {MAX_CALLS}")
    cursors = {}
    for key in ("before", "after"):
        value = args.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ToolError(f"{key} must be a non-negative integer (a cursor from the last answer)")
        cursors[key] = value
    texts = {}
    for key in ("feature", "connection", "model"):
        value = args.get(key)
        if value is not None and not isinstance(value, str):
            raise ToolError(f"{key} must be a string")
        texts[key] = value
    if args.get("range") not in (None, "24h", "7d", "30d"):
        raise ToolError("range must be 24h, 7d or 30d")
    if args.get("result") not in (None, "ok", "error"):
        raise ToolError("result must be ok or error")
    return _ok(_clean(await _via_route(ai_routes.recent_calls(
        limit, cursors["before"], cursors["after"], args.get("range"), texts["feature"], texts["connection"],
        texts["model"], args.get("result")))))


READ_TOOLS: dict = {
    "ai_connections_list": ("The configured AI connections (no keys), the per-capability defaults and the feature routing.",
                            {}, [], ai_connections_list),
    "ai_models_list": ("One AI connection's models, first 25 with models_total. Cached; refresh true asks the provider again; detail true lists all.",
                       {"connection_id": {"type": "string"}, "refresh": {"type": "boolean"}, "detail": {"type": "boolean"}}, ["connection_id"], ai_models_list),
    "ai_features_list": ("Every feature registered to use AI, its capability and where it is pointed.", {}, [],
                         ai_features_list),
    "ai_calls_list": ("One page of the newest AI calls: feature, connection, model, latency, tokens, cost, error, plus total, next and prev cursors. Never content.",
                      {"limit": {"type": "integer", "minimum": 1, "maximum": MAX_CALLS},
                       "before": {"type": "integer", "minimum": 0, "description": "cursor: the previous answer's next"},
                       "after": {"type": "integer", "minimum": 0, "description": "cursor: the previous answer's prev"},
                       "range": {"type": "string", "enum": ["24h", "7d", "30d"]},
                       "feature": {"type": "string"}, "connection": {"type": "string"}, "model": {"type": "string"},
                       "result": {"type": "string", "enum": ["ok", "error"]}}, [], ai_calls_list),
}
