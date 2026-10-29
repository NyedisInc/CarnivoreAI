
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from contextlib import closing
from typing import Any, Dict, List, Optional, Set

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request as HttpRequest
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api import pack_migrate_env as env_mod, pack_move_env, projects_service
from src.api.auth import require_auth
from src.api.project_replica_routes import find_peer
from src.config import settings
from src.core.federation import peer_links
from src.core.pack.move import inflight, op_status
from src.core.pack.identity import home
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.migrate import apply, live, ops, plan as plan_mod
from src.core.pack.move import ops as move_ops
from src.core.project_move.fingerprint import FingerprintError

logger = structlog.get_logger()
router = APIRouter()
pack_capabilities.register("pack.migrate")

BACK_TIMEOUT_SECONDS = 900.0
STATUS_FIELDS = ("running", "interrupted", "cancellable", "cancel_blocked", "machine", "direction")
_tasks: Set["asyncio.Task[Any]"] = set()


class MigrateBody(BaseModel):
    """Which machine, and whether to run. ``plan_fingerprint`` is the one the plan answered (required with ``apply``)."""

    model_config = ConfigDict(extra="forbid")

    machine: str = Field(min_length=1, max_length=200)
    apply: bool = False
    plan_fingerprint: Optional[str] = Field(default=None, max_length=64)
    rung: Optional[str] = Field(default=None, pattern="^(carried|tar)$")
    stop_running: bool = Field(default=False, description="interrupt every agent that is mid-turn, move, then tell those agents to continue on the other computer; off (default) refuses the move while any agent is running")


class BackBody(BaseModel):
    """Plan (default) or run a move back."""

    model_config = ConfigDict(extra="forbid")

    apply: bool = False


def _http(exc: plan_mod.MigrateError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "detail": exc.detail, "step": exc.step, "rule": exc.rule})


def _read_projects(selector: Any) -> List[Dict[str, Any]]:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        return selector(conn)


def _company_projects(conn: Any, company: str) -> List[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (int(company),)).fetchone() if company.isdigit() else \
        conn.execute("SELECT * FROM companies WHERE name = ? COLLATE NOCASE", (company,)).fetchone()
    if row is None:
        raise HTTPException(404, {"code": "unknown_company", "detail": f"no company {company!r}"})
    rows = [dict(r) for r in conn.execute("SELECT * FROM projects WHERE company_id = ? AND pack_state = 'home' AND archived_at IS NULL ORDER BY id", (row["id"],))]
    if not rows:
        raise HTTPException(409, {"code": "nothing_to_move", "detail": f"{row['name']} has no project that is active here"})
    return rows


async def _plans(projects: List[Dict[str, Any]], body: MigrateBody, env: plan_mod.SourceEnv) -> List[plan_mod.Plan]:
    peer = await run_in_threadpool(find_peer, body.machine)
    request = env_mod.link_request(peer.peer_install_id)
    if request is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": f"{peer.label} is not connected right now"})
    guarded = apply.guarded(request)
    try:
        return [await plan_mod.plan_project(env, p, peer.peer_install_id, guarded, rung=body.rung, stop_running=body.stop_running,
                                            target_caps=peer_links.LINKS.capabilities(peer.peer_install_id) if peer_links.LINKS is not None else ()) for p in projects]
    except plan_mod.MigrateError as exc:
        raise _http(exc) from exc


def _view(kind: str, name: str, plans: List[plan_mod.Plan]) -> Dict[str, Any]:
    fingerprint = plans[0].fingerprint if kind == "project" else hashlib.sha256("".join(p.fingerprint for p in plans).encode()).hexdigest()[:16]
    blocking = [f"{p.project['display_name']}: {b}" for p in plans for b in p.blocking]
    return {"kind": kind, "name": name, "machine": plans[0].target_label, "projects": [p.view() for p in plans], "blocking": blocking,
            "can_apply": not blocking, "plan_fingerprint": fingerprint}


def _launch(coro: Any, op_id: str, uids: List[str]) -> None:
    async def run() -> None:
        try:
            await coro
        except plan_mod.MigrateError as exc:
            logger.info("pack_migrate_failed", code=exc.code, step=exc.step)
        except Exception:  # noqa: BLE001
            logger.exception("pack_migrate_crashed")

    task = asyncio.get_running_loop().create_task(run())
    inflight.register(op_id, task, tuple(uids))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(kind: str, name: str, projects: List[Dict[str, Any]], body: MigrateBody, http_request: HttpRequest, company_uid: Optional[str] = None) -> Dict[str, Any]:
    if body.apply:
        projects_service.guard_writable(settings)
    hooks = pack_move_env.live_hooks(http_request.app.state)
    env = dataclasses.replace(env_mod.source_env(), find_live=hooks.session.find)
    plans = await _plans(projects, body, env)
    view = _view(kind, name, plans)
    if not body.apply:
        return view
    try:
        if not body.plan_fingerprint or not body.plan_fingerprint.strip():
            raise FingerprintError(428, "apply needs plan_fingerprint: ask for the plan first (apply false), read it, and send back its fingerprint")
        if body.plan_fingerprint.strip() != view["plan_fingerprint"]:
            raise FingerprintError(412, f"the plan changed since it was read (now {view['plan_fingerprint']}); read the new plan and quote it")
    except FingerprintError as exc:
        raise HTTPException(exc.status, {"code": "plan_fingerprint", "detail": str(exc), "plan": view}) from exc
    if view["blocking"]:
        raise HTTPException(409, {"code": "plan_blocked", "detail": "refused: " + "; ".join(view["blocking"]), "plan": view})
    uids = [p.project["uid"] for p in plans]
    peer = await run_in_threadpool(find_peer, body.machine)
    request, op_id = env_mod.link_request(peer.peer_install_id), ops.new_id()
    for uid in uids:
        running_op = inflight.op_for(uid)
        if running_op is not None:
            raise HTTPException(409, {"code": "migrate_in_progress", "detail": "this project is already being moved", "op_id": running_op})
    _launch(live.migrate(env, hooks, request, plans, kind=kind, company_uid=company_uid, op_id=op_id, stop_running=body.stop_running), op_id, uids)
    return {"op_id": op_id, "state": "applying", "plan": view}


@router.post("/projects/{project_name}/migrate", dependencies=[Depends(require_auth)])
async def migrate_project(project_name: str, body: MigrateBody, http_request: HttpRequest) -> Dict[str, Any]:
    """Plan, or plan and start, moving one project to a paired machine.

    Description: the plan names the rung (git clone, carried bundle, or one-way tar), the checks (live agents are listed and stopped by the move itself) and what moves.
      An agent that is mid-turn BLOCKS the plan (``agents_ready``) unless ``stop_running`` is true: then the move interrupts it (Escape), moves, and tells it to continue on the other computer.
      ``apply`` true quotes ``plan_fingerprint``; the answer is ``{op_id}`` and progress is ``GET /pack/ops/{op_id}``. The other
      computer verifies before it becomes home; then this project is ``moved_away`` here, kept, never deleted.
    Inputs: project_name; body (MigrateBody). Output: the plan view, or {op_id, state, plan}.
    Raises: 404 unknown project or machine, 409 ``project_moved_away`` / ``plan_blocked`` / ``migrate_in_progress`` or the other computer's
      refusal (403 ``pack_restricted`` with its ``rule``), 412 / 428 fingerprint, 502 ``machine_unreachable``.
    Example: POST /api/v1/projects/ledgerbot/migrate {"machine": "hosta"}
    """
    project = await run_in_threadpool(lambda: _read_projects(lambda c: projects_service.resolve_target(c, project_name)))
    return await _run("project", project["display_name"], [project], body, http_request)


@router.post("/companies/{company}/migrate", dependencies=[Depends(require_auth)])
async def migrate_company(company: str, body: MigrateBody, http_request: HttpRequest) -> Dict[str, Any]:
    """
    Output and raises: as ``migrate_project``; the plan lists every project. Example: POST /api/v1/companies/packproof/migrate {"machine": "hosta"}
    """
    def read(conn: Any) -> Dict[str, Any]:
        rows = _company_projects(conn, company)
        row = conn.execute("SELECT uid, name FROM companies WHERE id = ?", (rows[0]["company_id"],)).fetchone()
        return {"rows": rows, "uid": row["uid"], "name": row["name"]}

    found = await run_in_threadpool(lambda: _read_projects(read))
    return await _run("company", found["name"], found["rows"], body, http_request, company_uid=found["uid"])


@router.post("/projects/{project_name}/migrate-back", dependencies=[Depends(require_auth)])
async def migrate_back(project_name: str, body: BackBody) -> Dict[str, Any]:
    """Bring a moved-away project home: the machine that holds it plans and applies a migrate back here.
    """
    def read(conn: Any) -> Dict[str, Any]:
        project = projects_service.resolve_target(conn, project_name)
        if project["pack_state"] != home.MOVED_AWAY:
            raise HTTPException(409, {"code": "not_moved_away", "detail": "only a project that was moved to another computer can be brought back"})
        return {**project, "machine": home.machine_label(conn, project.get("moved_to_install_id"))}

    project = await run_in_threadpool(lambda: _read_projects(read))
    view = {"kind": "project", "name": project["display_name"], "machine": project["machine"], "will": f"{project['machine']} sends the project back here"}
    if not body.apply:
        return view
    projects_service.guard_writable(settings)
    request = env_mod.link_request(project["moved_to_install_id"], BACK_TIMEOUT_SECONDS)
    if request is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": f"{project['machine']} is not connected right now"})
    op_id = ops.new_id()
    try:
        status, answer = await apply.guarded(request)("POST", "/federation/pack/migrate/back", json={"op_id": op_id, "project_uid": project["uid"]})
    except plan_mod.MigrateError as exc:
        raise _http(exc) from exc
    if status != 200:
        detail = answer.get("detail") if isinstance(answer, dict) else None
        raise HTTPException(status if status in (404, 409, 412, 502) else 502, detail if isinstance(detail, dict) else {"code": "back_refused", "detail": "the other computer refused"})
    return {**answer, "op_id": op_id}


@router.get("/pack/ops/{op_id}", dependencies=[Depends(require_auth)])
async def get_op(op_id: str) -> Dict[str, Any]:
    """One transfer op: state, step, error_code, detail, (a company) children and the status fields (running, interrupted, cancellable, cancel_blocked, machine, direction). Raises 404 ``unknown_op``. Example: GET /api/v1/pack/ops/<id>"""
    def read() -> Optional[Dict[str, Any]]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            view = ops.view(conn, op_id) or move_ops.view(conn, op_id)
            status = op_status.one(conn, op_id)
            return None if view is None or status is None else {**view, **{k: status[k] for k in STATUS_FIELDS}}

    found = await run_in_threadpool(read)
    if found is None:
        raise HTTPException(404, {"code": "unknown_op", "detail": "no such migrate"})
    return found
