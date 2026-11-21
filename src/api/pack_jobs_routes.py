
from __future__ import annotations

import asyncio
import math
import re
from contextlib import closing
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.core.pack.errors.input_error import PackInputError
from src.api import project_replica_routes, projects_service
from src.api.auth import require_auth, security
from src.api.error_response import api_error
from src.config import settings
from src.core.api_keys.store import is_api_key
from src.core.attention.wiring_builders import spawn_held
from src.core.pack.identity import home, replicas as identity_replicas
from src.core.pack.jobs import boot, copy_run, place, policy, replicas, wipe
from src.core.pack.jobs.ssh import owner as ssh_owner
from src.core.pack.jobs.view import host_labels, host_view, job_view
from src.core.pack.jobs.types import TERMINAL, JobError, JobRecord, JobRequest
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.placement.workload import kind_from_task_type
from src.core.pack.transport import bundles

logger = structlog.get_logger()
router = APIRouter(tags=["pack-jobs"], dependencies=[Depends(require_auth)])

_HELD: Set["asyncio.Task[None]"] = set()


class JobBody(BaseModel):
    """What to run. Example: {"command": "pytest -q", "folder": "/Users/a/app"}."""

    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=8000)
    folder: str = Field(min_length=1, max_length=4096)
    kind: Optional[Literal["browser", "suite", "build", "render"]] = None
    outputs: List[str] = Field(default_factory=list, max_length=20)
    time_cap_minutes: int = Field(default=60, ge=1, le=360)

    def model_post_init(self, __context: Any) -> None:
        if any(len(o) > 256 for o in self.outputs):
            raise PackInputError("an output path is at most 256 characters")


class AutoDelegateBody(BaseModel):
    """The owner's choice for one project. Example: {"on": true, "never_use": ["tower"]}."""

    model_config = ConfigDict(extra="forbid")
    on: bool
    keep: Optional[str] = Field(default=None, max_length=200)
    wipe_others: bool = False
    delete_copies: bool = False
    delete_only: Optional[List[str]] = Field(default=None, max_length=50)
    never_use: Optional[List[str]] = Field(default=None, max_length=50)
    carry: Optional[List[str]] = Field(default=None, max_length=50)
    bring_back: Optional[List[str]] = Field(default=None, max_length=50)


def request_for(body: JobBody, caller_session: Optional[str]) -> JobRequest:
    if not body.folder.startswith("/"):
        raise JobError("folder_not_absolute", "the folder must be an absolute path", 422)
    kind = body.kind or kind_from_task_type(body.command)
    return JobRequest(command=body.command, folder=body.folder, kind="suite" if kind == "light" else kind,
                      caller_session=caller_session, outputs=list(body.outputs), time_cap_s=body.time_cap_minutes * 60)


def _job_error(exc: JobError) -> HTTPException:
    return api_error(exc.status, "job_refused" if exc.status == 409 else exc.code, exc)


def _engine() -> Any:
    try:
        return boot.engine()
    except JobError as exc:
        raise api_error(exc.status, exc.code, exc) from exc


def _known(eng: Any, job_id: str) -> JobRecord:
    rec = eng.get(job_id)
    if rec is None:
        raise api_error(404, "unknown_job")
    return rec


@router.post("/pack/jobs")
async def create_job(body: JobBody) -> Dict[str, Any]:
    """Run a command on the best computer now. Output: {job}. Raises 409 job_refused, 422 folder_not_absolute, 503 jobs_not_ready."""
    eng = _engine()
    try:
        return {"job": job_view(await eng.submit(request_for(body, None)))}
    except JobError as exc:
        raise _job_error(exc) from exc


_CURSOR_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _parse_cursor(text: Optional[str]) -> Optional[Tuple[float, str]]:
    if text is None:
        return None
    stamp, sep, ident = text.partition("|")
    try:
        at = float(stamp)
    except ValueError:
        raise api_error(422, "bad_cursor") from None
    if not sep or not math.isfinite(at) or not _CURSOR_ID.match(ident):
        raise api_error(422, "bad_cursor")
    return at, ident


def _page_view(store: Any, state_dir: Any, **query: Any) -> Dict[str, Any]:
    rows, more = store.list_page(**query)
    labels = host_labels(state_dir, [r.caller_install for r in rows if not hasattr(r, "id")])
    jobs = [job_view(r) if hasattr(r, "id") else host_view(r, labels.get(r.caller_install)) for r in rows]
    last = rows[-1] if rows else None
    cursor = f"{last.created_at!r}|{getattr(last, 'id', None) or last.job_id}" if more and last is not None else None
    return {"jobs": jobs, "next_before": cursor}


@router.get("/pack/jobs")
async def list_jobs(limit: int = 50, live: bool = False, before: Optional[str] = None, caller: Optional[str] = None,
                    project: Optional[str] = None) -> Dict[str, Any]:
    """The newest jobs, this computer's own (side caller) and those other computers sent here (side host), newest first.

    Inputs: limit 1 to 200; live=true keeps live jobs; before - the ``next_before`` of the previous page; caller - a calling session's
    uuid (drops host rows); project - a project uid. Output: {jobs, next_before} (next_before is None on the last page).
    Raises 422 bad_limit or bad_cursor.
    """
    if not 1 <= limit <= 200:
        raise api_error(422, "bad_limit")
    cursor = _parse_cursor(before)
    eng = _engine()
    return await run_in_threadpool(lambda: _page_view(eng.store, eng.store.state_dir, limit=limit, live_only=live, before=cursor,
                                                      caller=caller, project_uid=project))


@router.get("/pack/jobs/{job_id}")
async def get_job(job_id: str, wait: float = 0) -> Dict[str, Any]:
    """One job; ``wait`` (0 to 90 seconds) waits for it to end first. Output: {job}. Raises 404 unknown_job."""
    if not 0 <= wait <= 90:
        raise api_error(422, "bad_wait")
    eng = _engine()
    rec = _known(eng, job_id)
    if wait > 0:
        try:
            rec = await eng.wait(job_id, wait)
        except JobError as exc:
            raise api_error(exc.status, exc.code, exc) from exc
    return {"job": job_view(rec)}


@router.post("/pack/jobs/{job_id}/stop")
async def stop_job(job_id: str) -> Dict[str, Any]:
    """Stop one job. Output: {job}. Raises 404 unknown_job, 409 job_finished."""
    eng = _engine()
    if _known(eng, job_id).state in TERMINAL:
        raise api_error(409, "job_finished")
    try:
        return {"job": job_view(await eng.stop(job_id))}
    except JobError as exc:
        raise _job_error(exc) from exc




def _read_project(name: str) -> Dict[str, Any]:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        project = projects_service.resolve_target(conn, name)
        refusal: Optional[HTTPException] = None
        try:
            project_replica_routes._require_home(conn, project)
        except HTTPException as exc:
            refusal = exc
        state = project.get("pack_state")
        role = "copy" if state == home.REPLICA else "moved" if state == home.MOVED_AWAY else "home"
        from src.core.db import get_meta
        from src.core.db_models import META_INSTALL_ID

        other_id = project.get("home_install_id") if role == "copy" else project.get("moved_to_install_id")
        other = (home.machine_label(conn, other_id) or other_id) if other_id else None
        mine = get_meta(conn, META_INSTALL_ID)
        listed = identity_replicas.list_replicas(conn, project["uid"]) if role == "home" else []
        from src.core.computers.this_label import this_label

        own = home.machine_label(conn, mine)
        return {"project": project, "role": role, "refusal": refusal, "other": other, "replicas": listed, "install_id": mine,
                "label": this_label() if not own or own == mine else own}


async def _no_work(project: Dict[str, Any]) -> List[str]:
    try:
        pview = await asyncio.to_thread(place.live_view, project["root"], project["uid"])
    except JobError:
        return []
    return [p.install_id for p in pview.peers if place.unfit_reason(p, pview, project["uid"])]


async def _view(found: Dict[str, Any], eng: Any) -> Dict[str, Any]:
    project, uid = found["project"], found["project"]["uid"]
    pol = policy.get(eng.store, uid)
    held = {r["install_id"]: r for r in found["replicas"]}
    made = policy.auto_replicas(eng.store, uid)
    auto = [{"computer": (held.get(i) or {}).get("label") or i, "install_id": i, "created_at": (held.get(i) or {}).get("created_at")}
            for i in made]
    copies = [{"install_id": i, "label": r.get("label") or i, "auto": i in made, "root": r.get("root") or ""} for i, r in held.items()]
    live = await run_in_threadpool(lambda: len(eng.list(limit=200, project_uid=uid, live_only=True)))
    no_work = await _no_work(project)
    return {"role": "home", "project": project["display_name"], "project_uid": uid, "auto_delegate": pol.auto_delegate,
            "never_use": pol.never_use, "carry": pol.carry, "bring_back": pol.bring_back, "auto_replicas": auto,
            "this_computer": {"install_id": found["install_id"], "label": found["label"]},
            "is_repo": await run_in_threadpool(bundles.is_repo, project["root"]), "live_jobs": live, "copies": copies,
            "copy_run": copy_run.get(uid), "no_work": no_work}


@router.get("/projects/{project_name}/auto-delegate")
async def get_auto_delegate(project_name: str) -> Dict[str, Any]:
    """The project's mark, lists, copies and copy run; on a computer that is not its home only {role, home_computer or moved_to}."""
    found = await run_in_threadpool(_read_project, project_name)
    if found["role"] == "copy":
        return {"role": "copy", "home_computer": found["other"]}
    if found["role"] == "moved":
        return {"role": "moved", "moved_to": found["other"]}
    return await _view(found, _engine())


def _ensure_done(task: "asyncio.Task[None]") -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("pack_jobs_ensure_failed", error=type(task.exception()).__name__)


async def _ensure(eng: Any, name: str, uid: str, root: str) -> None:
    outcome: Dict[str, str] = {}
    error: Optional[str] = None
    completed = False
    try:
        await ssh_owner.seed_targets(eng.store, uid, root)
        view = await asyncio.to_thread(place.live_view, root, uid)
        outcome = await replicas.ensure_all(name, uid, store=eng.store, view=view, policy=policy.get(eng.store, uid))
        completed = True
        logger.info("pack_jobs_ensure_all", project_uid=uid, outcome=outcome)
    except JobError as exc:
        error = exc.code
        logger.warning("pack_jobs_ensure_refused", project_uid=uid, code=exc.code)
    finally:
        copy_run.finish(uid, outcome, error or (None if completed else "copy_run_failed"))
        home.notify_changed()


async def _keeper(found: Dict[str, Any], keep: Optional[str]) -> Optional[Dict[str, str]]:
    if keep is None or keep.strip() == str(found["install_id"]):
        return None
    try:
        peer = await run_in_threadpool(project_replica_routes.find_peer, keep)
    except HTTPException:
        if keep.strip().lower() == str(found["label"]).lower():
            return None
        raise api_error(409, "keep_unknown") from None
    row = next((r for r in found["replicas"] if r["install_id"] == peer.peer_install_id), None)
    if row is None:
        raise api_error(409, "keep_no_copy")
    try:
        pview = await asyncio.to_thread(place.live_view, found["project"]["root"], found["project"]["uid"])
    except JobError:
        raise api_error(409, "keep_offline") from None
    machine = next((p for p in pview.peers if p.install_id == peer.peer_install_id), None)
    if machine is None or not machine.usable:
        raise api_error(409, "keep_offline")
    if machine.snapshot is None or restrictions_mod.check(restrictions_mod.from_dict(machine.snapshot.get("restrictions")),
                                                          restrictions_mod.ACTION_RECEIVE_PROJECTS):
        raise api_error(409, "keep_cannot_receive")
    return {"machine": peer.peer_install_id, "label": row.get("label") or str(peer.label)}


def _made_copies(eng: Any, found: Dict[str, Any]) -> List[Dict[str, Any]]:
    held = {r["install_id"]: r for r in found["replicas"]}
    return [{"install_id": i, "label": (held.get(i) or {}).get("label") or i, "root": (held.get(i) or {}).get("root")}
            for i in policy.auto_replicas(eng.store, found["project"]["uid"])]


async def _owner_only(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    if credentials is not None and is_api_key(credentials.credentials):
        raise api_error(403, "mark_owner_only")


_OFF_LOCKS: Dict[str, asyncio.Lock] = {}


@router.put("/projects/{project_name}/auto-delegate", dependencies=[Depends(_owner_only)])
async def put_auto_delegate(project_name: str, body: AutoDelegateBody) -> Dict[str, Any]:
    """One change of the mark at a time per project: a second PUT (another tab, a retry) waits for the first to finish. See _put."""
    async with _OFF_LOCKS.setdefault(project_name.lower(), asyncio.Lock()):
        return await _put(project_name, body)


async def _put(project_name: str, body: AutoDelegateBody) -> Dict[str, Any]:
    eng = _engine()
    found = await run_in_threadpool(_read_project, project_name)
    if found["refusal"] is not None:
        raise found["refusal"]
    project = found["project"]
    uid = project["uid"]
    if body.on and not await run_in_threadpool(bundles.is_repo, project["root"]):
        raise api_error(409, "not_a_repo")
    keeper: Optional[Dict[str, str]] = None
    if body.on and body.delete_copies:
        raise api_error(422, "delete_copies_needs_off")
    if body.delete_copies and body.delete_only is None:
        raise api_error(422, "delete_only_required")
    if not body.on:
        keeper = await _keeper(found, body.keep)
        if await run_in_threadpool(lambda: eng.list(limit=1, project_uid=uid, live_only=True)):
            raise api_error(409, "jobs_running")
    if any(v is not None for v in (body.never_use, body.carry, body.bring_back)):
        try:
            policy.set_lists(eng.store, uid, never_use=body.never_use, carry=body.carry, bring_back=body.bring_back)
        except ValueError as exc:
            raise api_error(422, "bad_list", exc) from exc
    policy.set_auto(eng.store, uid, body.on)
    extra: Dict[str, Any] = {"replicas": "unchanged", "handoff": keeper, "deleted": [], "kept": [], "ssh_forgotten": [], "ssh_holding": []}
    if body.on:
        copy_run.start(uid)
        spawn_held(_ensure(eng, project["display_name"], uid, project["root"]), _HELD, _ensure_done)
        extra["replicas"] = "starting"
    elif body.wipe_others or body.delete_copies:
        tips, tips_code = await run_in_threadpool(wipe.home_tips, project["root"]) if body.delete_copies else ([], "")
        made = _made_copies(eng, found)
        if not body.wipe_others and body.delete_only is not None:
            made = [c for c in made if c["install_id"] in body.delete_only]
        done = await wipe.run({"name": project["display_name"], "uid": uid}, made, delete=body.delete_copies, detach_kept=body.wipe_others,
                              keep=keeper["machine"] if keeper else None, only=body.delete_only, tips=tips, tips_code=tips_code, store=eng.store)
        extra.update(done.wire())
        found = await run_in_threadpool(_read_project, project_name)
    if not body.on and body.delete_copies and body.wipe_others:
        extra["ssh_forgotten"] = await wipe.forget_ssh(eng.store, uid)
    if not body.on:
        extra["ssh_holding"] = await wipe.ssh_holding(eng.store, uid)
    if keeper is not None:
        policy.forget_auto_replica(eng.store, uid, keeper["machine"])
    home.notify_changed()
    return {**await _view(found, eng), **extra}


@router.post("/projects/{project_name}/auto-delegate/copy-check", dependencies=[Depends(_owner_only)])
async def copy_check(project_name: str) -> Dict[str, Any]:
    """The dry run of the turn-off's trash: ask every computer that holds a copy the mark made what it would do. Writes nothing anywhere.

    Output: {copies: [{install_id, label, root, verdict, code, ignored, ignored_more}], ssh_holding: [{key, label}] (the ssh computers
    holding the project's cache)}; ``verdict`` is ``deletable`` or ``kept`` and a
    kept row names its code (``needs_update`` for a computer without the capability, ``no_record`` for a copy the mark has no record of).
    Raises: 403 mark_owner_only (an API key), 409 not_project_home and project_moved_away, 404 unknown project.
    """
    eng = _engine()
    found = await run_in_threadpool(_read_project, project_name)
    if found["refusal"] is not None:
        raise found["refusal"]
    project = found["project"]
    made = _made_copies(eng, found)
    tips, tips_code = await run_in_threadpool(wipe.home_tips, project["root"]) if made else ([], "")
    return {"copies": await wipe.check_all({"uid": project["uid"]}, made, tips=tips, tips_code=tips_code),
            "ssh_holding": await wipe.ssh_holding(eng.store, project["uid"])}
