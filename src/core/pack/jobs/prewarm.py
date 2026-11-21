
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from pydantic import Field, field_validator

from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.identity import home as home_mod
from src.core.pack.jobs import folders, gitio, host_admit, paths, recipe
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import DepDir, DepDirWire, HostJob, HostState, JobError, _Wire
from src.core.pack.machines import capabilities
from src.core.pack.placement import workload

log = structlog.get_logger(__name__)

CAP_PREWARM = "pack.jobs.prewarm"
PATH = "/federation/pack/jobs/prewarm"
MARK = "warm-"
FREE_SLOTS_NEEDED = 2
TIME_CAP_S = 1800
SEND_TIMEOUT_S = 20.0
capabilities.register(CAP_PREWARM)


class PrewarmBody(_Wire):

    project_uid: str = Field(min_length=8, max_length=64)
    commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    dep_dirs: List[DepDirWire] = Field(default_factory=list, max_length=20)
    setup: Optional[List[str]] = Field(default=None, max_length=10)

    @field_validator("setup")
    @classmethod
    def _setup(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and any(not s or len(s) > 2000 or "\0" in s for s in v):
            raise ValueError("each setup step is 1 to 2000 characters")
        return v


def marker(project_uid: str) -> str:
    return MARK + hashlib.sha256(project_uid.encode()).hexdigest()[:16]


def _refusal(host: Any, caller: str, body: PrewarmBody, deps: List[DepDir]) -> Optional[str]:
    store: JobStore = host.store
    live = [r for r in store.host_list([HostState.PREPARING, HostState.RUNNING, HostState.PARKED]) if r.project_uid == body.project_uid]
    if any(r.job_id.startswith(MARK) for r in live):
        return "already warming this project"
    if live:
        return "a job of this project is running here"
    snap = host_admit.own_snapshot()
    if snap is None:
        return "this computer does not know its own load yet"
    battery = (snap or {}).get("battery")
    if isinstance(battery, dict) and battery.get("on_battery") is True:
        return "this computer is on battery"
    try:
        host_admit.check_pegged(snap)
    except JobError as exc:
        return exc.detail
    if folders.busy_count(store, body.project_uid) > host_admit.host_max_slots() - FREE_SLOTS_NEEDED:
        return "fewer than two job folders are free"
    if body.setup is not None:
        return "the project's own setup commands run every time, nothing to keep"
    rows = store.slot_rows(body.project_uid)
    if not deps:
        return "there is nothing to set up"
    if any(not r["job_id"] and not recipe.plan(r["path"], deps, r["memo"], None) for r in rows):
        return "a folder here is already set up for these lockfiles"
    try:
        host_admit._hold(host, marker(body.project_uid), caller, body.project_uid, workload.resolve({"kind": "build"}), TIME_CAP_S)  # noqa: SLF001
    except JobError as exc:
        return exc.detail or exc.code
    return None


def _commit_here(root: str, commit: str) -> bool:
    return gitio.run(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=root, check=False).returncode == 0


async def _warm(host: Any, project: Dict[str, Any], body: PrewarmBody, deps: List[DepDir], job_id: str, path: str, memo: Dict[str, str]) -> None:
    try:
        steps = recipe.plan(path, deps, memo, None, air_gap=bool(project.get("air_gap")))
        log_dir = Path(host.jobs_root) / "prewarm"
        log_dir.mkdir(parents=True, exist_ok=True)
        result = await recipe.run(steps, log_dir / f"{job_id}.log", timeout_s=TIME_CAP_S)
        memo.update(result.memo)
        log.info("pack_job_prewarm_done", job_id=job_id, ok=result.ok, steps=len(steps), seconds=round(result.seconds, 1))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("pack_job_prewarm_failed", job_id=job_id, error=type(exc).__name__)
    finally:
        await asyncio.to_thread(folders.release, host.store, path=path, memo=memo, now=host._clock())
        await asyncio.to_thread(host.store.host_delete, job_id)
        host_admit.drop(job_id)


async def prewarm(host: Any, caller: str, body: PrewarmBody) -> Dict[str, Any]:
    deps = [DepDir(d.path, d.kind, dict(d.locks), d.python) for d in body.dep_dirs]

    def start() -> Any:
        project = host._gate_sync(caller, body.project_uid)
        if project["pack_state"] == home_mod.HOME or caller != project["home_install_id"]:
            return "only this project's home computer may ask for a pre-warm"
        if not _commit_here(project["root"], body.commit):
            return "this computer does not have that commit yet"
        job_id = marker(body.project_uid)
        stale = host.store.host_get(job_id)
        if stale is not None and stale.state not in (HostState.PREPARING, HostState.RUNNING, HostState.PARKED):
            host.store.host_delete(job_id)
        reason = _refusal(host, caller, body, deps)
        if reason:
            return reason
        try:
            lease = folders.acquire(host.store, jobs_root=host.jobs_root, project_uid=body.project_uid, project_name=Path(project["root"]).name,
                                    repo_root=project["root"], commit=body.commit, job_id=job_id, max_slots=host_admit.host_max_slots())
        except JobError as exc:
            host_admit.drop(job_id)
            return exc.detail or exc.code
        host.store.host_put(HostJob(job_id=job_id, caller_install=caller, project_uid=body.project_uid, state=HostState.PREPARING,
                                    snapshot_commit=body.commit, time_cap_s=TIME_CAP_S))
        memo = dict(next((r["memo"] for r in host.store.slot_rows(body.project_uid) if r["path"] == lease.path), {}))
        return project, job_id, lease.path, memo

    got = await asyncio.to_thread(start)
    if isinstance(got, str):
        log.info("pack_job_prewarm_refused", project_uid=body.project_uid, reason=got[:120])
        return {"ok": False, "reason": got}
    project, job_id, path, memo = got
    host._track(job_id, _warm(host, project, body, deps, job_id, path, memo))
    return {"ok": True}


async def send(request: Any, project_uid: str, commit: str, dep_dirs: List[DepDir], setup: Optional[List[str]]) -> Dict[str, Any]:
    body = PrewarmBody(project_uid=project_uid, commit=commit, setup=setup,
                       dep_dirs=[DepDirWire(path=d.path, kind=d.kind, locks=d.locks, python=d.python) for d in dep_dirs]).model_dump()
    try:
        status, answer = await asyncio.wait_for(request("POST", PATH, json=body), SEND_TIMEOUT_S)
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError) as exc:
        return {"ok": False, "reason": f"unreachable ({type(exc).__name__})"}
    if status != 200 or not isinstance(answer, dict):
        detail = answer.get("detail") if isinstance(answer, dict) else None
        return {"ok": False, "reason": str(detail.get("code") if isinstance(detail, dict) else f"http_{status}")}
    return answer

