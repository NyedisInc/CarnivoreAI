
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra, session_target
from src.core.mcp.common import ToolError
from src.core.mcp.session_recovery_tools import redacted_read
from src.models.background_work import MAX_BATCH_TARGETS

MAX_START_CHARS = 64

_START_SCHEMA = {"type": "string", "minLength": 1, "maxLength": MAX_START_CHARS,
                 "description": "The start text exactly as session_background_jobs_list returned it."}
_PID_SCHEMA = {"type": "integer", "minimum": 1}


def _pid(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("pid must be a whole number of at least 1")
    return value


def _start(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_START_CHARS:
        raise ToolError(f"start must be the listing's start text, 1 to {MAX_START_CHARS} characters")
    return value


def _targets(args: dict) -> list[tuple[int, str]]:
    items = args.get("targets")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_TARGETS:
        raise ToolError(f"targets must be a list of 1 to {MAX_BATCH_TARGETS} {{pid, start}} objects")
    pairs = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"pid", "start"}:
            raise ToolError("each target is exactly {pid, start}")
        pairs.append((_pid(item["pid"]), _start(item["start"])))
    if len({pid for pid, _ in pairs}) != len(pairs):
        raise ToolError("each pid may appear once in targets")
    return pairs


def _stop_one(call: ra.Call) -> Any:
    from src.models.background_work import TerminateRequest

    return call.route(call.request, call.session_id, _pid(call.args.get("pid")), TerminateRequest(start=_start(call.args.get("start"))))


async def _stop_one_check(args: dict, _target: Any) -> None:
    _pid(args.get("pid"))
    _start(args.get("start"))


def _stop_many(call: ra.Call) -> Any:
    from src.models.background_work import TerminateAllRequest, TerminateTarget

    return call.route(call.request, call.session_id,
                      TerminateAllRequest(targets=[TerminateTarget(pid=pid, start=start) for pid, start in _targets(call.args)]))


async def _stop_many_check(args: dict, _target: Any) -> None:
    _targets(args)


def _background_set(call: ra.Call) -> Any:
    from src.models.themes import UpdateSessionBackgroundRequest

    theme_id, dim, disabled = (call.args.get(k) for k in ("theme_id", "dim", "disabled"))
    if theme_id is not None and (not isinstance(theme_id, str) or not 1 <= len(theme_id) <= 200):
        raise ToolError("theme_id must be an installed theme id from themes_list, or null")
    if dim is not None and (isinstance(dim, bool) or not isinstance(dim, (int, float))):
        raise ToolError("dim must be a number, or null")
    if disabled is not None and not isinstance(disabled, bool):
        raise ToolError("disabled must be true or false")
    return call.route(call.request, call.tmux_name, UpdateSessionBackgroundRequest(theme_id=theme_id, dim=dim, disabled=disabled is True))


SPECS = (
    redacted_read(
        name="session_all_tasks_list", route="src.api.session_tasks_routes:get_all_session_tasks",
        description="Every live session that keeps a task list, one entry per session with its tasks. Sessions with no list are "
                    "left out. Takes the page's short push lease.",
        invoke=lambda call: call.route(call.request),
    ),
    redacted_read(
        name="session_backgrounds_list", route="src.api.session_background_routes:list_session_backgrounds",
        description="Every per-session terminal background override (keyed by tmux name: theme id, dim, disabled), plus the default "
                    "dim. A session with no entry uses whatever its theme ships.",
        invoke=lambda call: call.route(call.request),
    ),
    ra.RouteTool(
        name="session_background_set", route="src.api.session_background_routes:set_session_background", gate=ra.ARRANGE,
        description="Set, change or clear one session's terminal background: theme_id borrows an installed theme's picture "
                    "(themes_list), dim is the scrim 0 to 1, disabled true paints none. Send nothing to clear the override.",
        properties={"theme_id": {"type": ["string", "null"], "maxLength": 200},
                    "dim": {"type": ["number", "null"], "description": "Scrim 0 to 1; the route clamps."}, "disabled": {"type": "boolean"}},
        reach=session_target.STORED, invoke=_background_set, example={"theme_id": "matrix", "dim": 0.4},
    ),
    ra.RouteTool(
        name="session_background_job_stop", route="src.api.session_background_work_routes:terminate_background_process", gate=ra.ACT,
        description="Stop one background process of a live Claude session and its subtree (SIGTERM, then SIGKILL). pid and start "
                    "come from session_background_jobs_list; the route refuses anything it does not measure as that session's own "
                    "descendant. Cannot be undone. Waits for the owner's approval unless Beast Mode is armed.",
        properties={"pid": _PID_SCHEMA, "start": _START_SCHEMA}, required=("pid", "start"),
        reach=session_target.LIVE, invoke=_stop_one, precheck=_stop_one_check, example={"pid": 4242, "start": "Mon Sep 28 08:58:46 2026"},
        summary=lambda args, target: f"stop background process {args.get('pid')} (and its children) in {target.shown if target else args.get('target')}",
    ),
    ra.RouteTool(
        name="session_background_jobs_stop", route="src.api.session_background_work_routes:terminate_background_processes", gate=ra.ACT,
        description=f"Stop a listed batch (1 to {MAX_BATCH_TARGETS}) of a live Claude session's background processes and their subtrees. "
                    "targets: {pid, start} pairs from session_background_jobs_list; a refused pair is reported per target and the rest "
                    "still run. Cannot be undone. Waits for the owner's approval unless Beast Mode is armed.",
        properties={"targets": {"type": "array", "minItems": 1, "maxItems": MAX_BATCH_TARGETS,
                                "items": {"type": "object", "properties": {"pid": _PID_SCHEMA, "start": _START_SCHEMA},
                                          "required": ["pid", "start"], "additionalProperties": False}}},
        required=("targets",), reach=session_target.LIVE, invoke=_stop_many, precheck=_stop_many_check,
        example={"targets": [{"pid": 4242, "start": "Mon Sep 28 08:58:46 2026"}]},
        summary=lambda args, target: (f"stop {len(args.get('targets') or [])} background process(es) and their children in "
                                      f"{target.shown if target else args.get('target')}"),
    ),
)

ALWAYS_WAIT_NAMES: frozenset = frozenset()

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
