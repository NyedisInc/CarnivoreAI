
from __future__ import annotations

from typing import Any, Optional

from src.cplugs.flow import service
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result


def _epoch(args: dict, key: str) -> Optional[float]:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ToolError(f"{key} must be epoch seconds")
    return float(value)


async def flow_get(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    seed = args.get("seed", "huddle_item")
    seed_id = args.get("id")
    if seed not in service.SEED_KINDS:
        raise ToolError(f"seed must be one of {', '.join(service.SEED_KINDS)}")
    if isinstance(seed_id, bool) or not isinstance(seed_id, (str, int)) or not str(seed_id).strip():
        raise ToolError("id is required: a task manager item number, or a session reference")
    try:
        run = await service.get_run(ctx, seed, str(seed_id).strip(), start=_epoch(args, "start"), end=_epoch(args, "end"),
                                    refresh=bool(args.get("refresh")))
    except service.SeedNotFound as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except service.ActivityUnavailable as exc:
        raise ToolError(f"a source is unavailable: {exc}") from exc
    if args.get("html"):
        return tool_result(service.as_page(scrub(run)))
    return tool_result(scrub(service.summarize(run, full=args.get("detail") == "full")))


TOOLS: dict[str, Any] = {
    "flow_get": ToolSpec(
        description=("Rebuild a multi-agent run as a swimlane flow chart: lanes (sessions, subagents nested), work blocks, "
                     "edges (crosstalk, spawn, subagent launch and return, task manager posts, owner replies) each with its source ids, "
                     "inferred edges marked. Seed: a task manager item number, or a session reference plus an optional window. "
                     "Read-only and on demand. With html=true the answer is {html}: ONE self-contained page (inline CSS and JS, "
                     "no network, under 2 MB) to post with task_manager_artifact_add."),
        properties={"seed": {"type": "string", "enum": list(service.SEED_KINDS)},
                    "id": {"type": ["string", "integer"]},
                    "start": {"type": "number", "minimum": 0}, "end": {"type": "number", "minimum": 0},
                    "refresh": {"type": "boolean"}, "html": {"type": "boolean"},
                    "detail": {"type": "string", "enum": ["summary", "full"]}},
        required=["id"], handler=flow_get, gate="read"),
}
