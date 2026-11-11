
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder

from src.core.mcp import restart_account_args, route_adapters as ra, session_control_tools, session_target
from src.core.mcp.common import ToolError

DEFAULT_RECORDS = 50
MAX_RECORDS = 200
MAX_NAME_CHARS = 200

_UUID_SCHEMA = {"type": "string", "minLength": 32, "maxLength": 64,
                "description": "A session_uuid, from session_resume_candidates_list or session_records_list."}


def _session_uuid(args: dict) -> str:
    value = args.get("session_uuid")
    try:
        uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ToolError("session_uuid must be a session UUID (see session_resume_candidates_list)") from None
    return value


def _name(args: dict, key: str, *, required: bool = True) -> Optional[str]:
    value = args.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME_CHARS:
        raise ToolError(f"{key} must be a tmux session name of 1 to {MAX_NAME_CHARS} characters")
    if value.startswith("remote:"):
        raise ToolError(f"{key} names a session on a paired computer: call the tool there")
    return value


def _limit(args: dict, default: int, maximum: int) -> int:
    limit = args.get("limit", default)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ToolError(f"limit must be a whole number from 1 to {maximum}")
    return limit


def redacted_read(**fields: Any) -> ra.RouteTool:
    return ra.RouteTool(gate=ra.READ, redact=True, **fields)


async def _records(call: ra.Call) -> Any:
    flags = {key: call.args.get(key, False) for key in ("include_automated", "archived_only")}
    if any(not isinstance(v, bool) for v in flags.values()):
        raise ToolError("include_automated and archived_only must be true or false")
    limit = _limit(call.args, DEFAULT_RECORDS, MAX_RECORDS)
    rows = jsonable_encoder(await call.route(call.request, **flags))
    rows = rows if isinstance(rows, list) else [rows]
    return {"records": rows[:limit], "total": len(rows)}


def _unarchive(call: ra.Call) -> Any:
    return call.route(call.request, _session_uuid(call.args))


def _adopt(call: ra.Call) -> Any:
    from src.models.adopt import AdoptSessionRequest

    return call.route(call.request, AdoptSessionRequest(session_name=_name(call.args, "session_name")))


async def _adopt_check(args: dict, _target: Any) -> None:
    _name(args, "session_name")


def _destroy(call: ra.Call) -> Any:
    return call.route(call.request, _name(call.args, "session_name"), confirm_name=None)


async def _destroy_check(args: dict, _target: Any) -> None:
    _name(args, "session_name")


def _recreate(call: ra.Call) -> Any:
    return session_control_tools._reopen_closed(call, call.args.get("agent_type"), *restart_account_args.read(call.args))


async def _recreate_check(args: dict, target: Any) -> None:
    account, pin = restart_account_args.read(args)
    agent = args.get("agent_type") or ((target.row or {}).get("agent_type") if target is not None else None)
    await restart_account_args.refuse_bad(account, pin, agent)


def _recreate_summary(args: dict, target: Any) -> str:
    on = restart_account_args.shown(args.get("account"), bool(args.get("always_use_account")))
    return f"start a new tmux session for {target.shown if target else args.get('target')} and resume its conversation{on}"


def _imported_restart(call: ra.Call) -> Any:
    from src.api.imported_restart_routes import ImportedRestartRequest

    return call.route(call.request, ImportedRestartRequest(session_uuid=_session_uuid(call.args), agent_type=_agent_type(call.args)))


def _agent_type(args: dict) -> str:
    value = args.get("agent_type")
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME_CHARS:
        raise ToolError("agent_type must be a wrapper id from session_imported_restart_preview")
    return value


async def _imported_check(args: dict, _target: Any) -> None:
    _session_uuid(args)
    _agent_type(args)


SPECS = (
    redacted_read(
        name="session_restart_preview", route="src.api.restart_routes:restart_preview",
        description="What restarting a live session would do, changing nothing: the pane's state and one predicted outcome per launch "
                    "wrapper, from a single reading of the pane. Use its wrapper ids with session_restart.",
        reach=session_target.LIVE, invoke=lambda call: call.route(call.request, call.tmux_name),
    ),
    redacted_read(
        name="session_recreate_preview", route="src.api.recreate_routes:recreate_preview",
        description="What recreating an asleep or closed session would do, changing nothing: whether its tmux session is gone and one "
                    "predicted outcome per launch wrapper. Use its wrapper ids with session_recreate.",
        reach=session_target.CLOSED, needs_uuid=True, invoke=lambda call: call.route(call.session_uuid),
    ),
    redacted_read(
        name="session_imported_restart_preview", route="src.api.imported_restart_routes:imported_restart_preview",
        description="What restarting an imported conversation (no tmux session of its own) would do, changing nothing: one predicted "
                    "outcome per launch wrapper. session_uuid comes from session_resume_candidates_list.",
        properties={"session_uuid": _UUID_SCHEMA}, required=("session_uuid",),
        invoke=lambda call: call.route(_session_uuid(call.args)),
        example={"session_uuid": "aaaaaaaa-1111-4111-8111-111111111111"},
    ),
    redacted_read(
        name="session_records_list", route="src.api.session_records_routes:list_session_records",
        description="Stored session rows on this computer, newest first, archived ones included (total says how many exist). "
                    "archived_only: only archived rows (find a session_uuid for session_record_unarchive); include_automated: add "
                    "scheduler and headless runs; limit: 1 to 200, default 50.",
        properties={"include_automated": {"type": "boolean"}, "archived_only": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RECORDS}},
        invoke=_records, example={"archived_only": True},
    ),
    ra.RouteTool(
        name="session_record_unarchive", route="src.api.session_records_routes:unarchive_session_record", gate=ra.ARRANGE,
        description="Bring an archived session record back onto the owner's lists (the reverse of archiving it). Idempotent: an "
                    "already visible row answers 'already visible'. session_uuid comes from session_records_list archived_only.",
        properties={"session_uuid": _UUID_SCHEMA}, required=("session_uuid",), invoke=_unarchive,
        example={"session_uuid": "aaaaaaaa-1111-4111-8111-111111111111"},
    ),
    ra.RouteTool(
        name="session_adopt", route="src.api.session_attach_routes:adopt_session", gate=ra.ACT,
        description="Adopt a tmux session started outside Carnivore (session_name from session_adoption_candidates_list) as a managed "
                    "session; the pane keeps running. Refused when the pane is already dead. Waits for the owner's approval unless "
                    "Beast Mode is armed.",
        properties={"session_name": {"type": "string", "maxLength": MAX_NAME_CHARS}}, required=("session_name",),
        invoke=_adopt, precheck=_adopt_check, example={"session_name": "outside_tmux"},
        summary=lambda args, target: f"adopt the outside tmux session {args.get('session_name')} as a managed session",
    ),
    ra.RouteTool(
        name="session_recreate", route="src.api.recreate_routes:recreate_session", gate=ra.ACT,
        description="Start a new tmux session for an asleep or closed one whose tmux session is gone, on the row it already has, "
                    "resuming its conversation (target its session_uuid; see session_recreate_preview for wrapper ids). A session whose "
                    "tmux is still present is refused. agent_type defaults to the row's own. Waits for the owner's approval unless Beast Mode is armed.",
        properties={"agent_type": {"type": "string", "maxLength": MAX_NAME_CHARS, "description": "A launch wrapper id."},
                    **restart_account_args.PROPERTIES},
        reach=session_target.CLOSED, needs_uuid=True, invoke=_recreate, precheck=_recreate_check, summary=_recreate_summary,
        example={"agent_type": "claude"},
    ),
    ra.RouteTool(
        name="session_imported_restart", route="src.api.imported_restart_routes:imported_restart", gate=ra.ACT,
        description="Start a tmux session for an imported conversation and resume it under a launch wrapper (agent_type from "
                    "session_imported_restart_preview). Refused while a restart of that row is already running. Waits for the "
                    "owner's approval unless Beast Mode is armed.",
        properties={"session_uuid": _UUID_SCHEMA, "agent_type": {"type": "string", "maxLength": MAX_NAME_CHARS}},
        required=("session_uuid", "agent_type"), invoke=_imported_restart, precheck=_imported_check,
        summary=lambda args, target: f"start an imported conversation ({args.get('session_uuid')}) under {args.get('agent_type')} and resume it",
        example={"session_uuid": "aaaaaaaa-1111-4111-8111-111111111111", "agent_type": "claude"},
    ),
    ra.RouteTool(
        name="session_external_stop", route="src.api.session_attach_routes:destroy_external_session", gate=ra.ACT,
        description="Kill a tmux session on Carnivore's socket that is NOT a managed session, by name (a dead outside pane, for "
                    "instance). The session manager refuses only a name bound to a live managed "
                    "session (use session_delete for that); a Swarm leader is refused by the route. Cannot be undone. Always waits for the owner's approval.",
        properties={"session_name": {"type": "string", "maxLength": MAX_NAME_CHARS}},
        required=("session_name",), invoke=_destroy, precheck=_destroy_check, example={"session_name": "outside_tmux"},
        summary=lambda args, target: f"kill the outside tmux session {args.get('session_name')} (cannot be undone)",
    ),
)

ALWAYS_WAIT_NAMES = frozenset({"session_external_stop"})

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
