from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
import structlog
from pydantic import BaseModel, ConfigDict, StrictBool

from src.api.error_response import api_error, refusal_error
from src.api.auth import require_auth
from src.api import automation_timers_listing
from src.api.automation_list_view import list_view
from src.core.automations import models as m
from src.core.db import DatastoreUnreadableError
from src.core.automations import contract, pause, recipes, run_by, run_feed, schedule, schedule_nl, session_tree, targets
from src.core.byoai import gateway as byoai_gateway
from src.models.automations import CONTRACT_PATCH_FIELDS, UNATTENDED_PHRASE, AutomationCreate, AutomationPatch, ScheduleParse, SchedulePreview

logger = structlog.get_logger()

router = APIRouter(prefix="/automations", tags=["automations"], dependencies=[Depends(require_auth)])

PREVIEW_FIRES = 5
_CONFLICTS = frozenset({"already_running", "name_taken", "not_live"})


def get_store(request: Request) -> Any:
    store = getattr(request.app.state, "automation_store", None)
    if store is None:
        raise HTTPException(503, detail={"code": "automations_unavailable"})
    return store


def get_scheduler(request: Request) -> Any:
    scheduler = getattr(request.app.state, "automation_scheduler", None)
    if scheduler is None:
        raise HTTPException(503, detail={"code": "automations_unavailable"})
    return scheduler


def refuse(exc: Exception) -> HTTPException:
    if isinstance(exc, m.AutomationNotFound):
        return HTTPException(404, detail={"code": "not_found"})
    if isinstance(exc, m.AutomationInvalid):
        return refusal_error(exc, status=409 if exc.code in _CONFLICTS else 422)
    raise exc


def require_unattended_phrase(target: Any, phrase: Any) -> None:
    if isinstance(target, dict) and target.get("kind") == "agent" and target.get("permission") == "unattended" and phrase != UNATTENDED_PHRASE:
        raise HTTPException(422, detail={"code": "unattended_not_acknowledged", "message": f'type "{UNATTENDED_PHRASE}"'})


def stamp_phrase(target: Any, phrase: Any) -> Any:
    if isinstance(target, dict) and target.get("kind") == "agent" and target.get("permission") == "unattended":
        return {**target, "acknowledge_unattended": phrase}
    return target


def run_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    return {**{k: v for k, v in run.items() if k != "report"}, "has_report": bool(run.get("report_bytes"))}


async def _with_last_run(store: Any, automation: Dict[str, Any]) -> Dict[str, Any]:
    latest = await asyncio.to_thread(store.runs, automation["automation_id"], 1)
    return {**automation, "last_run": run_summary(latest[0]) if latest else None}


async def _with_table_fields(store: Any, view: Dict[str, Any]) -> Dict[str, Any]:
    rows = view["automations"]
    extras = await asyncio.to_thread(run_feed.table_fields, store, rows)
    try:
        inputs = await asyncio.to_thread(session_tree.read_inputs)
        listed = {s["session_uuid"]: s for s in inputs["sessions"] if s.get("session_uuid") and not s.get("archived_at")}
        project_ids: Optional[set] = {p["id"] for p in inputs["projects"] if p.get("id") is not None}
    except (OSError, sqlite3.Error, DatastoreUnreadableError) as exc:
        logger.warning("automations.list.files_under_unavailable", error=type(exc).__name__)
        listed, project_ids = {}, None
    return {**view, "tz": run_feed.zone_name(),
            "automations": [{**a, **extras[a["automation_id"]], "files_under": session_tree.file_of(a, listed, project_ids)} for a in rows]}


async def check_project(project_id: Any) -> None:
    problem = await asyncio.to_thread(contract.project_problem, project_id)
    if problem:
        raise HTTPException(422, detail={"code": problem, "message": f"project {project_id}"})


def actor_of(request: Any) -> Dict[str, Any]:
    who = getattr(request, "automation_actor", None)
    return who if isinstance(who, dict) and who.get("kind") in contract.ACTOR_KINDS else contract.actor("app")


@router.get("")
async def list_automations(request: Request, project_id: int = Query(default=0, ge=0), session: Optional[str] = Query(default=None, max_length=200),
                           enabled: Optional[bool] = Query(default=None), target_kind: Optional[str] = Query(default=None, max_length=40),
                           group_by: Optional[str] = Query(default=None, max_length=20)):
    """Every automation with its next fire time and its last run's summary, optionally narrowed (all filters AND together):
    ``project_id`` one project's; ``session`` (a session_uuid, ``ses_`` id or tmux name, live or asleep) those whose target names it
    or whose project is its project; ``enabled``; ``target_kind``. ``group_by=session`` answers ``{group_by, tree}`` instead: the
    sessions tab's projects > sessions > automations tree with an ``unassigned`` node (nodes with nothing in them are dropped when a
    filter is on). Either shape also carries ``scheduler: {paused}``, the global pause (#1495), and ``timers_status: {state, total,
    enabled}``, the one status word for every automation (``core/automations/timer_status.py``, #1639). 404 ``session_not_found``, 422
    ``group_by_invalid`` / ``target_kind_invalid``. Without ``group_by`` the answer also carries ``tz`` (the IANA zone cron is
    evaluated in) and, on each automation, ``recent`` (its 12 newest runs, newest first), ``median_took_s``, ``newest_output_empty``,
    ``run_count``, ``newest_number``, ``spends`` and ``files_under`` ({session_uuid, project_id}, both null = unassigned). Pushed:
    re-read when the ``automations`` / ``automation_runs`` topics are named."""
    view = await list_view(request, get_store(request), _with_last_run, project_id, session, enabled, target_kind, group_by)
    paused = await asyncio.to_thread(pause.is_paused)
    store = get_store(request)
    if group_by is None:
        view = await _with_table_fields(store, view)
    return {**view, "scheduler": {"paused": paused},
            "timers_status": await asyncio.to_thread(automation_timers_listing.global_status, store, paused)}


def check_include(include: Optional[str]) -> bool:
    if include not in (None, run_feed.INCLUDE_REPORT):
        raise HTTPException(422, detail={"code": "include_invalid", "message": f"include can only be {run_feed.INCLUDE_REPORT!r}"})
    return include == run_feed.INCLUDE_REPORT


def feed_run(run: Dict[str, Any]) -> Dict[str, Any]:
    out = run_summary(run)
    if "report_omitted" in run:
        out["report_omitted"] = run["report_omitted"]
        if not run["report_omitted"]:
            out["report"] = run.get("report")
    return out


async def list_recent_runs(request: Request, before: str = "", limit: int = 30) -> Dict[str, Any]:
    return await feed_view(get_store(request), before, limit, [], [], [], [], False, [], False)


async def feed_view(store: Any, before: str, limit: int, automation_ids: List[str], statuses: List[str], triggers: List[str],
                    hosts: List[str], no_host: bool, counters: List[str], with_report: bool) -> Dict[str, Any]:
    found = await asyncio.to_thread(run_feed.feed, store, before=before, limit=limit, automation_ids=automation_ids, statuses=statuses,
                                    triggers=triggers, hosts=hosts, no_host=no_host, counters=counters, with_report=with_report)
    return {**found, "runs": [{**feed_run(r), "automation_name": r["automation_name"]} for r in found["runs"]]}


@router.get("/runs")
async def list_feed_runs(request: Request, before: str = Query(default="", max_length=80), limit: int = Query(default=30, ge=1, le=120),
                         automation_id: List[str] = Query(default=[]), status: List[str] = Query(default=[]),
                         trigger: List[str] = Query(default=[]), host: List[str] = Query(default=[]), no_host: bool = Query(default=False),
                         counter: List[str] = Query(default=[]), include: Optional[str] = Query(default=None, max_length=20)):
    """Run history across every automation, newest first, live runs included, paged by ``before`` (a run id), as
    ``{runs, total, next_before}``. Each run carries its automation's ``automation_name``. Filters: ``automation_id``, ``status``,
    ``trigger``, ``host`` and ``counter`` repeat (OR within one, AND across kinds); ``no_host`` also takes runs with no recorded
    computer (ORs with ``host``); ``counter`` is one of succeeded_24h, failed_24h, succeeded_7d, failed_7d, skipped_7d,
    produced_nothing_7d, running, waiting_on_you (422 ``counter_invalid``). ``total`` counts every match, all pages. Reports are
    left out unless ``include=report`` (422 ``include_invalid`` otherwise): then each run carries ``report`` and ``report_omitted``,
    and once the response holds 4 MiB of report text the rest are ``report_omitted: true`` with no ``report`` (fetch the run).
    Pushed: re-read when the ``automation_runs`` topic is named."""
    unknown = [c for c in counter if c not in run_feed.COUNTER_IDS]
    if unknown:
        raise HTTPException(422, detail={"code": "counter_invalid", "message": f"unknown counter {unknown[0][:40]!r}"})
    return await feed_view(get_store(request), before, limit, automation_id, status, trigger, host, no_host, counter, check_include(include))


@router.get("/run-counts")
async def get_run_counts(request: Request) -> Dict[str, Any]:
    """The eight run counters the page's strip shows, counted over every stored run (never from loaded pages): ``counters`` maps
    each id (succeeded_24h, failed_24h, succeeded_7d, failed_7d, skipped_7d, produced_nothing_7d, running, waiting_on_you) to
    ``{count, automation_ids}``; ``hosts`` the distinct computers seen; ``has_unrecorded_host`` whether runs stored before the
    computer was recorded exist; ``next_change_at`` the instant a counted run next leaves its 24 h or 7 d window (null when none).
    Declared before ``/{automation_id}``. Pushed: re-read when the ``automations`` / ``automation_runs`` topics are named."""
    return await asyncio.to_thread(run_feed.counts, get_store(request))


class SchedulerPause(BaseModel):
    """The body of a pause switch: ``paused`` true holds every scheduled run, false lets them fire again."""

    model_config = ConfigDict(extra="forbid")
    paused: StrictBool


@router.get("/scheduler")
async def get_scheduler_state() -> Dict[str, Any]:
    """The scheduler's global pause. Output: {paused}."""
    return {"paused": await asyncio.to_thread(pause.is_paused)}


@router.put("/scheduler")
async def put_scheduler_state(body: SchedulerPause) -> Dict[str, Any]:
    """Pause or resume the scheduler: while paused every scheduled run is skipped ``scheduler_paused`` (run now still runs, and no
    automation's own switch changes). Output: {paused}. 503 ``config_unwritable`` when config.json cannot be written."""
    try:
        return {"paused": await asyncio.to_thread(pause.set_paused, body.paused)}
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise api_error(503, "config_unwritable", exc) from exc


@router.post("")
async def create_automation(request: Request, body: AutomationCreate):
    """Save an automation. 422 ``interval_under_15_min``, ``never_fires``, ``cron_invalid``, ``target_invalid``, ``target_not_available``,
    ``unattended_not_acknowledged``; 409 ``name_taken``."""
    store = get_store(request)
    require_unattended_phrase(body.target, body.acknowledge_unattended)
    body.target = stamp_phrase(body.target, body.acknowledge_unattended)
    await check_project(body.project_id)
    who = actor_of(request)
    try:
        return await asyncio.to_thread(store.create, name=body.name, cron=body.cron, target=body.target, delivery=body.delivery,
                                       enabled=body.enabled, created_by=who["kind"], actor=who,
                                       **{k: getattr(body, k) for k in CONTRACT_PATCH_FIELDS})
    except (m.AutomationInvalid, m.AutomationNotFound) as exc:
        raise refuse(exc) from exc


@router.post("/schedule/preview")
async def preview_schedule(body: SchedulePreview):
    """The next five fires of a cron string (machine-local and UTC), or the reason it is refused. Read-only."""
    now = datetime.now(timezone.utc).timestamp()
    try:
        compiled = schedule.compile_cron(body.cron, now)
    except m.AutomationInvalid as exc:
        return {"ok": False, "reason": exc.code}
    return {"ok": True, "fires": _fires(compiled, now)}


def _fires(compiled: Any, now: float, zone: Optional[ZoneInfo] = None) -> List[Dict[str, str]]:
    fires: List[Dict[str, str]] = []
    after = now
    while len(fires) < PREVIEW_FIRES:
        after = schedule.next_epoch(compiled, after)
        if after is None:
            break
        stamp = datetime.fromtimestamp(after, tz=timezone.utc)
        row = {"utc": stamp.isoformat(), "local": stamp.astimezone().isoformat()}
        if zone is not None:
            row["in_zone"] = stamp.astimezone(zone).isoformat()
        fires.append(row)
    return fires


@router.post("/schedule/parse")
async def parse_schedule(body: ScheduleParse):
    """A plain-English schedule as a cron string, through the owner's connected AI (BYOAI feature ``automations.schedule``).

    Sends the model only the sentence and the zone name. Answers ``{ok: true, cron, explain, fires}`` (the next five, each with
    ``in_zone`` in the caller's zone beside the machine-local time cron actually runs on) or ``{ok: false, reason, message}``:
    ``no_ai_connection``, ``ai_timeout``, ``ai_error``, ``ai_output_invalid``, ``ai_refused``, or the parser's own ``cron_invalid``,
    ``interval_under_15_min``, ``never_fires``. NEVER saves anything; the client shows it for confirmation. No MCP tool: this
    route is the API surface and agents write cron directly.
    """
    try:
        zone = ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return schedule_nl.refusal("timezone_invalid")
    answer = await schedule_nl.interpret(body.text, body.timezone, chat=byoai_gateway.get_gateway().chat)
    if not answer["ok"]:
        return answer
    now = datetime.now(timezone.utc).timestamp()
    return {**answer, "fires": _fires(schedule.compile_cron(answer["cron"], now), now, zone)}


@router.get("/targets")
async def list_targets():
    """The target kinds that have a runner on this install, each recipe and system action with its params schema (drives the
    picker), and the command allow-list's names (empty until the owner names commands)."""
    from src.core.automations import system_actions  # noqa: PLC0415
    from src.core.automations import command_allowlist  # noqa: PLC0415

    listed = {**recipes.REGISTRY, **system_actions.REGISTRY}
    return {"kinds": sorted(targets.RUNNERS),
            "recipes": [{"recipe": name, "system_action": name in system_actions.REGISTRY,
                         "params_schema": model.model_json_schema()} for name, (model, _run) in listed.items()],
            "commands": await asyncio.to_thread(command_allowlist.read)}


@router.get("/{automation_id}")
async def get_automation(request: Request, automation_id: str):
    """One automation."""
    try:
        return await asyncio.to_thread(get_store(request).get, automation_id)
    except m.AutomationNotFound as exc:
        raise refuse(exc) from exc


@router.patch("/{automation_id}")
async def update_automation(request: Request, automation_id: str, body: AutomationPatch):
    """Edit an automation at the revision the editor read. 409 ``revision_conflict`` carries the server's copy; 422 as for create."""
    store = get_store(request)
    fields = ("name", "cron", "target", "delivery", "enabled", *CONTRACT_PATCH_FIELDS)
    changes = {k: getattr(body, k) for k in fields if k in body.model_fields_set}
    if "target" in changes:
        require_unattended_phrase(changes["target"], body.acknowledge_unattended)
        changes["target"] = stamp_phrase(changes["target"], body.acknowledge_unattended)
    if changes.get("project_id") is not None:
        await check_project(changes["project_id"])
    try:
        return await asyncio.to_thread(store.update, automation_id, body.revision, actor=actor_of(request), **changes)
    except m.RevisionConflict as exc:
        current = await asyncio.to_thread(store.get, automation_id)
        raise HTTPException(409, detail={"code": "revision_conflict", "automation": current}) from exc
    except (m.AutomationInvalid, m.AutomationNotFound) as exc:
        raise refuse(exc) from exc


@router.delete("/{automation_id}")
async def delete_automation(request: Request, automation_id: str):
    """Delete an automation: any live run of it is cancelled first; a seeded one leaves a tombstone so the seed never re-adds it."""
    store, scheduler = get_store(request), get_scheduler(request)
    try:
        await asyncio.to_thread(store.get, automation_id)
        for run in await asyncio.to_thread(store.live_runs):
            if run["automation_id"] == automation_id:
                await scheduler.cancel_run(run["run_id"])
        await asyncio.to_thread(store.delete, automation_id, actor_of(request))
    except (m.AutomationInvalid, m.AutomationNotFound) as exc:
        raise refuse(exc) from exc
    return {"deleted": automation_id}


@router.get("/{automation_id}/changes")
async def list_changes(request: Request, automation_id: str, before: int = Query(default=0, ge=0),
                       limit: int = Query(default=20, ge=1, le=100)):
    """The change log, newest first: who created, edited or deleted it, each with its before/after diff. A deleted
    automation's log stays readable (an id with no log at all is an empty list)."""
    rows = await asyncio.to_thread(get_store(request).changes, automation_id, limit, before or None)
    return {"changes": rows}


def _pressed_by(request: Request) -> Dict[str, Any]:
    who = actor_of(request)
    owner = run_by.owner_name(getattr(request.app.state, "ui_preferences_store", None)) if who.get("kind") == "app" else None
    return run_by.with_name(who, run_by.main_db_path(), owner)


@router.post("/{automation_id}/run")
async def run_automation_now(request: Request, automation_id: str):
    """Run now, outside the schedule. 409 ``already_running``; the gates still apply and a skip comes back as the run row.

    Who pressed it (the owner in the app, with the owner's name, or the agent behind the MCP call, with its session's
    name) is kept in the run's ``notes.by`` (``run_by.with_name``), which the developer widget's scheduled tab shows as
    "run now by ..."."""
    by = await asyncio.to_thread(_pressed_by, request)
    try:
        return run_summary(await get_scheduler(request).run_now(automation_id, by=by))
    except (m.AutomationInvalid, m.AutomationNotFound) as exc:
        raise refuse(exc) from exc


async def list_runs(request: Request, automation_id: str, before: str = "", limit: int = 20, with_report: bool = False) -> Dict[str, Any]:
    store = get_store(request)
    try:
        await asyncio.to_thread(store.get, automation_id)
    except m.AutomationNotFound as exc:
        raise refuse(exc) from exc
    rows = await asyncio.to_thread(store.runs, automation_id, limit, before or None)
    return {"runs": [feed_run(r) for r in (run_feed.apply_report_budget(rows) if with_report else rows)]}


@router.get("/{automation_id}/runs")
async def list_automation_runs(request: Request, automation_id: str, before: str = Query(default="", max_length=80),
                               limit: int = Query(default=20, ge=1, le=50), include: Optional[str] = Query(default=None, max_length=20)):
    """Run history, newest first, paged by ``before`` (a run id). Reports are left out unless ``include=report`` (same
    ``report`` / ``report_omitted`` rule and 4 MiB budget as ``GET /automations/runs``): fetch a run for its report."""
    return await list_runs(request, automation_id, before, limit, check_include(include))
