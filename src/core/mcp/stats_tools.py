
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError
from src.models.stats import Dimension, ImpactMetric, QueryBatchRequest, QueryRequest, Resolution

MAX_PAGE_ROWS = 200
MAX_CURSOR = 100000
DEFAULT_CONTRIBUTION_ROWS = 50
DEFAULT_EVENT_ROWS = 100
MAX_CONVERSATIONS = 500

_ISO = "ISO-8601 with a UTC offset, such as 2026-11-01T00:00:00Z"
_FILTERS = {
    "provider": {"type": "string", "enum": ["claude", "codex"]},
    "host": {"type": "string"}, "project": {"type": "string"}, "model": {"type": "string"},
    "agent_kind": {"type": "string"}, "conversation_id": {"type": "string"},
}
_RANGE = {"from": {"type": "string", "description": f"Start, {_ISO}."}, "to": {"type": "string", "description": f"End, {_ISO}."}}
_PAGE = {"cursor": {"type": "integer", "minimum": 0, "maximum": MAX_CURSOR, "description": "Rows to skip. Default 0."}}


def _read(**fields: Any) -> ra.RouteTool:
    return ra.RouteTool(gate=ra.READ, redact=True, **fields)


def _int(args: dict, key: str, default: int, low: int, high: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ToolError(f"{key} must be a whole number from {low} to {high}")
    return value


def _when(args: dict, key: str, *, required: bool = True) -> datetime | None:
    raw = args.get(key)
    if raw is None:
        if required:
            raise ToolError(f"{key} is required, {_ISO}")
        return None
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"{key} must be {_ISO}") from exc


def _text(args: dict, key: str) -> str | None:
    value = args.get(key)
    if value is not None and not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _uuid(args: dict, key: str) -> UUID:
    try:
        return UUID(str(args[key]))
    except (KeyError, ValueError) as exc:
        raise ToolError(f"{key} must be an id from the matching list tool") from exc


def _filters(args: dict, *, extra: tuple[str, ...] = ()) -> dict:
    return {key: _text(args, key) for key in (*_FILTERS, *extra)}


def _contributions(call: ra.Call) -> Any:
    metric = _text(call.args, "metric")
    if not metric:
        raise ToolError("metric is required: an id from stats_catalog_get")
    return call.route(
        call.request, metric=metric, from_=_when(call.args, "from"), to=_when(call.args, "to"),
        timezone_name=_text(call.args, "timezone") or "UTC", resolution=_text(call.args, "resolution") or "auto",
        **_filters(call.args), limit=_int(call.args, "limit", DEFAULT_CONTRIBUTION_ROWS, 1, MAX_PAGE_ROWS),
        cursor=_int(call.args, "cursor", 0, 0, MAX_CURSOR))


def _dimensions(call: ra.Call) -> Any:
    dimension = _text(call.args, "dimension")
    if dimension not in Dimension.__args__:
        raise ToolError(f"dimension must be one of {', '.join(Dimension.__args__)}")
    return call.route(
        call.request, dimension=dimension, from_=_when(call.args, "from", required=False),
        to=_when(call.args, "to", required=False), **_filters(call.args, extra=("account_id", "window")),
        limit=_int(call.args, "limit", DEFAULT_CONTRIBUTION_ROWS, 1, MAX_PAGE_ROWS),
        cursor=_int(call.args, "cursor", 0, 0, MAX_CURSOR))


def _annotations(call: ra.Call) -> Any:
    return call.route(
        call.request, from_=_when(call.args, "from"), to=_when(call.args, "to"),
        limit=_int(call.args, "limit", DEFAULT_EVENT_ROWS, 1, MAX_PAGE_ROWS), cursor=_int(call.args, "cursor", 0, 0, MAX_CURSOR),
        **_filters(call.args))


def _event_log(call: ra.Call) -> Any:
    return call.route(
        call.request, from_=_when(call.args, "from"), to=_when(call.args, "to"), kind=_text(call.args, "kind"),
        limit=_int(call.args, "limit", DEFAULT_EVENT_ROWS, 1, MAX_PAGE_ROWS), cursor=_int(call.args, "cursor", 0, 0, MAX_CURSOR))


def _conversations(call: ra.Call) -> Any:
    return call.route(
        call.request, from_=_when(call.args, "from"), to=_when(call.args, "to"), provider=_text(call.args, "provider"),
        project=_text(call.args, "project"), model=_text(call.args, "model"),
        limit=_int(call.args, "limit", MAX_CONVERSATIONS, 1, MAX_CONVERSATIONS))


def _impact(call: ra.Call) -> Any:
    metric = call.args.get("metric", "estimated_cost_nano_usd")
    if metric not in ImpactMetric.__args__:
        raise ToolError(f"metric must be one of {', '.join(ImpactMetric.__args__)}")
    return call.route(call.request, annotation_id=_uuid(call.args, "annotation_id"), metric=metric,
                      days=_int(call.args, "days", 7, 1, 30))


_QUERY_PROPERTIES = {
    "metric": {"type": "string", "description": "A metric id from stats_catalog_get."},
    "operation": {"type": "string", "enum": ["summary", "timeline", "ranking", "comparison"], "description": "Default timeline."},
    **_RANGE,
    "rolling": {"type": "string", "enum": ["1h", "6h", "24h", "7d", "30d", "90d"], "description": "A trailing window that replaces from and to."},
    "timezone": {"type": "string"}, "resolution": {"type": "string", "enum": list(Resolution.__args__)},
    "filters": {"type": "object", "description": "Exact-match filters: provider, host, project, model, agent_kind, conversation_id, ..."},
    "group_by": {"type": "string", "enum": list(Dimension.__args__)},
    "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
    "transform": {"type": "string", "enum": ["total", "rate", "cumulative", "per_conversation"]},
    "comparison": {"type": "object", "description": "The range to compare against: {from, to}."},
    "scope": {"type": "string", "enum": ["local", "pack"], "description": "pack adds the paired computers' rollups."},
}


def _query(call: ra.Call) -> Any:
    return call.route(call.request, QueryRequest.model_validate(call.args))


def _query_batch(call: ra.Call) -> Any:
    return call.route(call.request, QueryBatchRequest.model_validate(call.args))


def _chart(call: ra.Call) -> Any:
    return call.route(call.request, _uuid(call.args, "chart_id"))


def _tripwire(call: ra.Call) -> Any:
    return call.route(call.request, _uuid(call.args, "tripwire_id"))


SPECS = (
    _read(
        name="stats_catalog_get", route="src.api.stats_routes:get_catalog", invoke=lambda call: call.route(),
        description="Every stats metric id with its unit and the operations it supports. Read this before stats_query_run.",
    ),
    _read(
        name="stats_settings_get", route="src.api.stats_routes:get_settings", invoke=lambda call: call.route(call.request),
        description="Whether stats collection is on, and the settings revision. Stats reads answer stats_off while it is off.",
    ),
    _read(
        name="stats_coverage_get", route="src.api.stats_routes:get_coverage", invoke=lambda call: call.route(call.request),
        description="The time span the stats store holds, plus the collector status and progress.",
    ),
    _read(
        name="stats_maintenance_get", route="src.api.stats_maintenance_routes:get_maintenance",
        invoke=lambda call: call.route(call.request),
        description="Stats database size, the clear job's state and the backfill progress.",
    ),
    _read(
        name="stats_live_get", route="src.api.stats_routes:get_live", invoke=lambda call: call.route(call.request),
        description="The live stats snapshot: scheduler metrics plus the cached live view while stats are on.",
    ),
    _read(
        name="stats_query_run", route="src.api.stats_routes:post_query", invoke=_query, properties=_QUERY_PROPERTIES,
        required=("metric",), example={"metric": "total_tokens", "rolling": "24h"},
        description="Run one stats query: a metric over a range, as a summary, timeline, ranking or comparison. Read-only. Use rolling "
                    "or from and to; group_by splits by a dimension.",
    ),
    _read(
        name="stats_query_batch_run", route="src.api.stats_routes:post_query_batch", invoke=_query_batch,
        properties={"items": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "object"},
                              "description": "Up to 32 stats_query_run bodies; each answers on its own."}},
        required=("items",), example={"items": [{"metric": "total_tokens", "rolling": "24h"}]},
        description="Run up to 32 stats queries in one call, each item a stats_query_run body. One bad item does not fail the rest.",
    ),
    _read(
        name="stats_contributions_list", route="src.api.stats_routes:get_contributions", invoke=_contributions,
        properties={"metric": {"type": "string"}, **_RANGE, "timezone": {"type": "string"}, "resolution": {"type": "string"},
                    **_FILTERS, "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_ROWS}, **_PAGE},
        required=("metric", "from", "to"), example={"metric": "total_tokens", "from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
        description="What contributed to a metric over a range: ranked contributors, paged. limit 1 to 200, default 50.",
    ),
    _read(
        name="stats_dimensions_list", route="src.api.stats_routes:get_dimensions", invoke=_dimensions,
        properties={"dimension": {"type": "string", "enum": list(Dimension.__args__)}, **_RANGE, **_FILTERS,
                    "account_id": {"type": "string"}, "window": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_ROWS}, **_PAGE},
        required=("dimension",), example={"dimension": "model"},
        description="The distinct values of one stats dimension (project, model, host...), paged, optionally within a range and filters.",
    ),
    _read(
        name="stats_conversations_list", route="src.api.stats_insight_routes:get_conversations", invoke=_conversations,
        properties={**_RANGE, "provider": _FILTERS["provider"], "project": {"type": "string"}, "model": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_CONVERSATIONS}},
        required=("from", "to"), example={"from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z", "limit": 10},
        description="The costliest conversations of a range: duration, cost, tokens, project and model. limit 1 to 500, default 500.",
    ),
    _read(
        name="stats_impact_get", route="src.api.stats_insight_routes:get_impact", invoke=_impact,
        properties={"annotation_id": {"type": "string"}, "metric": {"type": "string", "enum": list(ImpactMetric.__args__)},
                    "days": {"type": "integer", "minimum": 1, "maximum": 30}},
        required=("annotation_id",), example={"annotation_id": "00000000-0000-4000-8000-000000000001"},
        description="A per-conversation metric the days before against the days after one marker, with a confidence interval. "
                    "annotation_id comes from stats_annotations_list.",
    ),
    _read(
        name="stats_events_list", route="src.api.stats_event_routes:get_event_log", invoke=_event_log,
        properties={**_RANGE, "kind": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_ROWS}, **_PAGE},
        required=("from", "to"), example={"from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
        description="Typed stats events in a range, newest first, ids and numbers only. kind narrows by event kind. limit 1 to 200, default 100.",
    ),
    _read(
        name="stats_annotations_list", route="src.api.stats_routes:get_events", invoke=_annotations,
        properties={**_RANGE, **_FILTERS, "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_ROWS}, **_PAGE},
        required=("from", "to"), example={"from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
        description="The owner's chart markers (annotations) in a range, paged. limit 1 to 200, default 100.",
    ),
    _read(
        name="stats_charts_list", route="src.api.stats_routes:get_charts", invoke=lambda call: call.route(call.request),
        description="Every saved stats chart: id, kind, options, title and revision.",
    ),
    _read(
        name="stats_chart_get", route="src.api.stats_routes:get_chart", invoke=_chart,
        properties={"chart_id": {"type": "string"}}, required=("chart_id",),
        example={"chart_id": "00000000-0000-4000-8000-000000000001"},
        description="One saved stats chart by id, from stats_charts_list.",
    ),
    _read(
        name="stats_tripwires_list", route="src.api.stats_tripwire_routes:list_tripwires",
        invoke=lambda call: call.route(call.request),
        description="Every stats tripwire (a threshold alarm on a metric) with its current state.",
    ),
    _read(
        name="stats_tripwire_get", route="src.api.stats_tripwire_routes:get_tripwire", invoke=_tripwire,
        properties={"tripwire_id": {"type": "string"}}, required=("tripwire_id",),
        example={"tripwire_id": "00000000-0000-4000-8000-000000000001"},
        description="One stats tripwire by id, from stats_tripwires_list.",
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
