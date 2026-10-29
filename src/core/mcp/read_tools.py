
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _ok
from src.core.provider_ledger import pace

MAX_ROWS = 50


def scrub(value: Any) -> Any:
    from src.core.mcp.tools import redact_text

    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if "token" not in str(k).lower()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return redact_text(value) if isinstance(value, str) else value


async def _route(coro: Any) -> Any:
    try:
        return await coro
    except HTTPException as exc:
        raise ToolError(f"unavailable ({exc.status_code})") from exc


async def usage_ledger(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.provider_ledger_routes import get_provider_ledger

    snap = await _route(get_provider_ledger())
    now = datetime.now(timezone.utc)
    accounts = []
    for a in snap.accounts:
        windows = []
        for w in a.windows:
            length = pace.window_length_seconds(w.kind, w.label, w.window_seconds)
            elapsed = pace.elapsed_pct(length, w.resets_at, now)
            windows.append({"kind": w.kind, "label": w.label, "used_pct": w.used_pct,
                            "elapsed_pct": elapsed, "pace": pace.pace_state(w.used_pct, elapsed),
                            "resets_at": w.resets_at})
        accounts.append({"id": a.id, "name": a.name, "provider": a.provider, "plan": a.plan,
                         "credential_state": a.credential_state, "error": a.error,
                         "fetched_at": a.fetched_at, "windows": windows})
    return _ok(scrub({"accounts": accounts}))


async def stats_feed(manager: Any, caller: AgentCaller, args: dict) -> dict:
    import json

    from src.api.stats_feed_routes import get_stats_feed
    from src.core.mcp.write_tools import _request
    from src.core.stats_feed import install

    window = args.get("window", "1h")
    if not isinstance(window, str):
        raise ToolError("window must be one of 1h, 5h, 1d, 7d")
    request = _request(manager)
    doc = json.loads((await _route(get_stats_feed(request, window=window, lease=False))).body)
    doc["diagnostics"] = install(request.app.state).diagnostics()
    return _ok(scrub(doc))


async def pipeline_status(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.pipeline_plugin_routes import pipeline_status as route

    return _ok(scrub(await _route(route())))


async def alerts_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.app_alerts_routes import list_alerts

    return _ok(scrub(await _route(list_alerts(state="active", limit=MAX_ROWS))))


async def notification_destinations_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.notifications import doc_model, routing_view, types
    from src.core.notifications.destinations.service import current_service
    from src.core.notifications.settings_doc import view

    service = current_service()
    if service is None:
        raise ToolError("unavailable (notifications have not started)")
    doc = service.docs.snapshot()
    statuses = routing_view.current_statuses()
    rows = []
    for dest_id in view.dest_ids(doc):
        item = view.destination_dict(doc, dest_id)
        if item is None:
            continue
        st = statuses.get(dest_id)
        if not item["enabled"]:
            word = "disabled"
        elif st is None or (st.last_ok_ts is None and st.last_failure_ts is None):
            word = "untested"
        else:
            word = "failing" if (st.last_failure_ts or 0) > (st.last_ok_ts or 0) else "ok"
        rows.append({"kind": item["kind"], "name": item["name"], "enabled": item["enabled"], "scope": item["scope"],
                     "status": word,
                     "ticked_types": [r.id for r in types.ordered_types() if view.cell(doc, dest_id, r.id).value]})
    return _ok(scrub({"destinations": rows}))


async def transcript_manifest(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.transcript_manifest_routes import get_manifest

    filters = {}
    for name in ("status", "kind", "family", "conversation_id"):
        value = args.get(name)
        if value is not None and not isinstance(value, str):
            raise ToolError(f"{name} must be a string")
        filters[name] = value
    limit = args.get("limit", MAX_ROWS)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ToolError("limit must be a positive integer")
    return _ok(scrub(await _route(get_manifest(limit=min(limit, MAX_ROWS), offset=0, **filters))))


async def self_check(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.self_check_routes import get_self_check

    return _ok(scrub(await _route(get_self_check())))


MAX_PROFILE_SECONDS = 60


async def perf_profile(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.mcp import lean_answers
    from src.api.perf_routes import ProfileBody, post_profile

    full = lean_answers.detail_flag(args)
    seconds = args.get("seconds", 20)
    top = args.get("top", 25 if full else lean_answers.PROFILE_TOP)
    for name, value, high in (("seconds", seconds, MAX_PROFILE_SECONDS), ("top", top, MAX_ROWS)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
            raise ToolError(f"{name} must be an integer from 1 to {high}")
    result = await _route(post_profile(ProfileBody(seconds=seconds, top=top)))
    return _ok(scrub(result if full else lean_answers.profile(result, top)))


async def session_git_status(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.session_git_routes import get_session_git_status
    from src.core.mcp.write_tools import _request

    from src.core.mcp.session_target import live_info

    info = await live_info(manager, args, "session_git_status")
    status = await _route(get_session_git_status(_request(manager), info.session.id))
    return _ok(scrub(status.model_dump()))


async def session_attach_command(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.session_attach_command_routes import get_session_attach_command
    from src.core.mcp.write_tools import _request

    from src.core.mcp.session_target import live_info

    info = await live_info(manager, args, "session_attach_command")
    answer = await _route(get_session_attach_command(_request(manager), info.session.id))
    return _ok(scrub(answer.model_dump()))


TOOLS: dict = {
    "usage_ledger": ("Per account and window: used percent, elapsed percent, pace verdict, reset time.", {}, [], usage_ledger),
    "stats_feed": ("Tokens in and out for all accounts on this computer and paired computers: a trailing rate and the "
                   "last 1h, 5h, 1d or 7d; stats off or paused are named, never zeros.",
                   {"window": {"type": "string", "enum": ["1h", "5h", "1d", "7d"]}}, [], stats_feed),
    "self_check": ("Carnivore's own health: critical files not iCloud placeholders, free space, tmux, claude CLI, disk access. PASS/FAIL per check.", {}, [], self_check),
    "alerts_list": ("List the app's active alerts (what is raising a badge or banner for the owner) with the badge counts, capped. Read only.", {}, [], alerts_list),
    "notification_destinations_list": ("Notification destinations: kind, name, enabled, scope, delivery status and the "
                                       "notification types ticked for each. Never a URL, recipient or secret.",
                                       {}, [], notification_destinations_list),
    "pipeline_status": ("The pipeline engine's state (caught up, behind, stalled or rebuilding), "
                        "lag, last delivery, per-plugin failures and the recent runs (one row per session, project or machine and "
                        "plugin: run time, finished at, runs since boot, outcome), what is running now and the queue (the next keys and "
                        "the total).", {}, [], pipeline_status),
    "transcript_manifest": (
        "Transcript file manifest: every claude and codex transcript on disk with size, mtime, last line serial "
        "and offset, and whether it was added, grew, was rewritten or removed; summary counts and the last scan.",
        {"status": {"type": "string", "enum": ["present", "grown", "rewritten", "gone"]},
         "kind": {"type": "string", "enum": ["conversation", "subagent", "other"]},
         "family": {"type": "string", "enum": ["claude", "codex"]},
         "conversation_id": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}},
        [], transcript_manifest,
    ),
    "session_git_status": ("What changed in one session's repository since HEAD: branch, ahead/behind, counts, changed files "
                           "(capped), state ok, not_a_repo, remote or unknown (never read as clean).",
                           {"target": _TARGET_SCHEMA}, ["target"], session_git_status),
    "session_attach_command": ("The argv that attaches a terminal to one local session (resolved tmux, socket, "
                               "attach-session, =<name>); run it without a shell. Launches nothing; a paired "
                               "computer's session is refused.",
                               {"target": _TARGET_SCHEMA}, ["target"], session_attach_command),
    "perf_profile": (
        "Profile the Carnivore server's own CPU for a few seconds: CPU per thread, hottest Python stacks and "
        "functions, subprocess launches, directory reads, file opens and sqlite connects per calling line, GC time. "
        "Top 15 rows, stacks cut to 8 frames; detail true gives 25 rows and whole stacks.",
        {"seconds": {"type": "integer", "minimum": 1, "maximum": MAX_PROFILE_SECONDS},
         "detail": {"type": "boolean", "description": "full answer instead of the lean default"},
         "top": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}},
        [], perf_profile,
    ),
}
