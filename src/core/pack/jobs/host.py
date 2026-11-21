
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

import structlog

from src.core.pack.jobs import bundle_io, collect, folders, gitio, host_admit, paths, recipe, runner
from src.core.pack.jobs.agent_host import TASK_EXCLUDE, AgentDeps, AgentHost
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import (AdmitBody, CollectAnswer, DepDir, HostJob, HostState, JobError, JobIdBody, ReplyBody, StartBody,
                                      StatusAnswer, StopBody)
from src.core.pack.machines.restrictions import ACTION_HOST_AGENTS, Restrictions, enforce, live_agents as _live_agents
from src.core.pack.placement import workload
from src.core.pack.transport import blobs

log = structlog.get_logger(__name__)

MAX_SLOTS = 3
KEEP_HOURS = 24
PURGE_AFTER_S = 24 * 3600
COLLECTED_HOLD_S = 3600
STALE_RUN_GRACE_S = 600
STOP_WAIT_S = 120.0


def default_restrictions() -> Restrictions:
    from src.core.pack.machines import config_state

    return config_state.default().restrictions()


def default_admit(work: workload.Workload) -> Optional[str]:
    from src.core.pack.reserve import local
    from src.core.swarm import admission

    reserve: Optional[admission.Reserve] = None
    try:
        active = local.active_reserve()
        if active:
            reserve = admission.Reserve(active["cpu_pct"], active["mem_pct"], active["level"])
    except (OSError, ValueError) as exc:
        log.info("pack_jobs_reserve_unreadable", error=type(exc).__name__)
    return admission.refusal(admission.measure(), 0, None, reserve=reserve, est_cpu_cores=work.est_cpu_cores, est_ram_gb=work.est_ram_gb)


def default_request_for(install_id: str) -> blobs.Request:
    from src.core.federation import peer_links

    client = peer_links.LINKS.client(install_id) if peer_links.LINKS is not None else None
    if client is None:
        raise JobError("unreachable", "the other computer is not connected", 502)
    return blobs.request_via(client, timeout=300.0)


def _replace_roots(command: str, roots: List[str], slot: str) -> str:
    for root in sorted({r.rstrip("/") or "/" for r in roots}, key=len, reverse=True):
        command = re.sub(re.escape(root) + r"(?=$|[/\s\"':;)])", lambda _m: slot, command)
    return command


async def _uninterruptible(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    fut = asyncio.ensure_future(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        await asyncio.wait({fut})
        if not fut.cancelled():
            fut.exception()
        raise


class Host:

    def __init__(self, *, state_dir: Path, jobs_root: Path, install_id: str, socket: str = paths.JOBS_TMUX_SOCKET,
                 store: Optional[JobStore] = None, open_db: Optional[Callable[[], sqlite3.Connection]] = None,
                 restrictions: Callable[[], Restrictions] = default_restrictions, live_agents: Callable[[], int] = _live_agents,
                 admit: Callable[[workload.Workload], Optional[str]] = default_admit,
                 request_for: Callable[[str], blobs.Request] = default_request_for,
                 spawn: Callable[[Coroutine[Any, Any, None]], "asyncio.Task[None]"] = asyncio.ensure_future,
                 clock: Callable[[], float] = time.time, agent_deps: Optional[AgentDeps] = None) -> None:
        from src.core.db import connect, db_path_for

        self.state_dir, self.jobs_root, self.install_id, self.socket = Path(state_dir), Path(jobs_root), install_id, socket
        self.store = store or JobStore(self.state_dir)
        self._open_db = open_db or (lambda: connect(db_path_for(self.state_dir), create=False))
        self._restrictions, self._live_agents, self._admit = restrictions, live_agents, admit
        self._request_for, self._spawn, self._clock = request_for, spawn, clock
        self._tasks: Dict[str, "asyncio.Task[None]"] = {}
        self._memo: Dict[str, Dict[str, str]] = {}
        self.agent = AgentHost(self)
        if agent_deps is not None:
            self.agent.bind(agent_deps)


    def _agent_jobs_live(self) -> int:
        live = (HostState.PREPARING, HostState.RUNNING, HostState.PARKED)
        return sum(1 for row in self.store.host_list(live) if row.body == "agent")

    def _gate_sync(self, caller: str, project_uid: str, *, new_agent: bool = False) -> Dict[str, Any]:
        from src.core.pack.identity import home, replicas

        with closing(self._open_db()) as conn:
            row = conn.execute("SELECT p.*, c.uid AS company_uid FROM projects p "
                               "LEFT JOIN companies c ON c.id = p.company_id WHERE p.uid = ?", (project_uid,)).fetchone()
            if row is None or row["pack_state"] == home.MOVED_AWAY:
                raise JobError("project_not_here", "this computer does not hold that project", 409)
            project = dict(row)
            counterparts = {r["install_id"] for r in replicas.list_replicas(conn, project_uid)} if project["pack_state"] == home.HOME \
                else {project["home_install_id"]}
        if caller not in counterparts:
            raise JobError("not_a_counterpart", "that computer is neither this project's home nor its replica", 403)
        enforce(self._restrictions(), ACTION_HOST_AGENTS, project_uid=project_uid, company_uid=project["company_uid"],
                live_agents=self._live_agents() + (self._agent_jobs_live() if new_agent else 0))
        return project

    def _row(self, caller: str, job_id: str) -> HostJob:
        row = self.store.host_get(job_id)
        if row is None or row.caller_install != caller:
            raise JobError("unknown_job", "no such job", 404)
        return row

    def _gated_row(self, caller: str, job_id: str) -> "tuple[HostJob, Dict[str, Any]]":
        row = self._row(caller, job_id)
        return row, self._gate_sync(caller, row.project_uid)


    def _meta(self, job_id: str) -> Path:
        return paths.meta_dir(self.jobs_root, job_id)

    def _meta_read(self, job_id: str) -> Dict[str, Any]:
        try:
            return json.loads((self._meta(job_id) / "job.json").read_text())
        except (OSError, ValueError):
            return {}

    def _meta_write(self, job_id: str, data: Dict[str, Any]) -> None:
        target = self._meta(job_id) / "job.json"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)


    async def admit(self, caller: str, body: AdmitBody) -> Dict[str, Any]:
        def run() -> None:
            self._gate_sync(caller, body.project_uid, new_agent=bool(body.agent_family))
            if body.agent_family:
                self.agent.check(caller, body.agent_family, body.account_key)
            tag: Dict[str, Any] = {"kind": body.kind}
            if body.est_cpu is not None:
                tag["est_cpu_cores"] = body.est_cpu
            if body.est_ram_gb is not None:
                tag["est_ram_gb"] = body.est_ram_gb
            work = workload.resolve(tag)
            host_admit.admit(self, caller, body, work)

        try:
            await asyncio.to_thread(run)
        except ValueError as exc:
            raise JobError("bad_request", str(exc), 422) from exc
        return {"ok": True}

    async def start(self, caller: str, body: StartBody) -> Dict[str, Any]:
        def sync() -> "tuple[Optional[HostJob], str, str]":
            existing = self.store.host_get(body.job_id)
            project = self._gate_sync(caller, body.project_uid, new_agent=body.agent is not None and existing is None)
            if existing is not None:
                if existing.caller_install != caller:
                    raise JobError("unknown_job", "no such job", 404)
                return existing, project["root"], ""
            if body.agent is not None:
                self.agent.check(caller, body.agent.family, body.agent.account_key)
            tag: Dict[str, Any] = {"kind": body.kind}
            if body.est_cpu is not None:
                tag["est_cpu_cores"] = body.est_cpu
            if body.est_ram_gb is not None:
                tag["est_ram_gb"] = body.est_ram_gb
            try:
                work = workload.resolve(tag)
            except ValueError as exc:
                raise JobError("bad_request", str(exc), 422) from exc
            host_admit.start_hold(self, caller, body.job_id, body.project_uid, work)
            try:
                path = bundle_io.received_path(self.state_dir, body.snapshot_blob_id, sender=caller)
            except blobs.BlobError as exc:
                raise JobError(exc.code, "the snapshot blob is not here", exc.status) from exc
            root = Path(project["root"])
            root.mkdir(parents=True, exist_ok=True)
            if not (root / ".git").exists():
                gitio.run(["init", "-q"], cwd=str(root))
            git_dir = gitio.out(gitio.run(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=str(root)))
            if not bundle_io.verify(git_dir, str(path)):
                raise JobError("bundle_unverified", "the snapshot bundle does not verify against this computer's copy of the project", 409)
            self._meta_write(body.job_id, {"outputs": body.outputs, "deps": [d.path for d in body.dep_dirs], "scope": body.scope,
                                           "changed": None, "air_gap": bool(body.air_gap) or bool(project.get("air_gap"))})
            self.store.host_put(HostJob(job_id=body.job_id, caller_install=caller, project_uid=body.project_uid, state=HostState.PREPARING,
                                        snapshot_commit=body.snapshot_commit, time_cap_s=body.time_cap_s, **self.agent.row_fields(body)))
            return None, str(root), git_dir

        existing, root, git_dir = await asyncio.to_thread(sync)
        if existing is not None:
            return {"ok": True, "state": existing.state.value}
        self._track(body.job_id, self._prepare(caller, body, root, git_dir))
        return {"ok": True, "state": HostState.PREPARING.value}

    def _track(self, job_id: str, coro: Coroutine[Any, Any, None]) -> None:
        task = self._spawn(coro)
        self._tasks[job_id] = task
        task.add_done_callback(lambda t, j=job_id: self._tasks.pop(j, None))

    def _free_job_slots(self, job_id: str, project_uid: str, *, keep_hours: float = 0, now: Optional[float] = None) -> None:
        host_admit.drop(job_id)
        for r in self.store.slot_rows(project_uid):
            if r["job_id"] == job_id:
                folders.release(self.store, path=r["path"], memo=self._memo.pop(job_id, None), keep_hours=keep_hours,
                                now=self._clock() if now is None else now)

    def _free_orphan_slots(self, now: float) -> None:
        live = {r.job_id for r in self.store.host_list([HostState.PREPARING, HostState.RUNNING, HostState.PARKED, HostState.EXITED])}
        for r in self.store.slot_rows():
            if r["job_id"] and r["job_id"] not in live:
                log.warning("pack_job_slot_orphan_freed", job_id=r["job_id"])
                folders.release(self.store, path=r["path"], now=now)

    async def _prepare(self, caller: str, body: StartBody, root: str, git_dir: str) -> None:
        started = {"session": False}
        try:
            def fetch() -> str:
                path = bundle_io.received_path(self.state_dir, body.snapshot_blob_id, sender=caller)
                got = bundle_io.fetch_bundle(git_dir, str(path), f"refs/heads/job-{body.job_id}", f"refs/carnivore/jobs/{body.job_id}/snapshot")
                if got != body.snapshot_commit:
                    raise JobError("snapshot_mismatch", "the bundle holds a different commit than the one announced", 409)
                bundle_io.consumed(self.state_dir, body.snapshot_blob_id)
                parent = gitio.run(["rev-parse", "--verify", "-q", f"{got}^"], git_dir=git_dir, check=False)
                if parent.returncode == 0:
                    gitio.run(["update-ref", f"refs/carnivore/jobs-base/{caller}", gitio.out(parent)], git_dir=git_dir, check=False)
                return got

            commit = await _uninterruptible(fetch)
            project_name = Path(root).name
            lease = await _uninterruptible(
                folders.acquire, self.store, jobs_root=self.jobs_root, project_uid=body.project_uid, project_name=project_name,
                repo_root=root, commit=commit, job_id=body.job_id, max_slots=MAX_SLOTS)
            slot = lease.path
            self.store.host_set(body.job_id, slot_path=slot)
            memo = dict(next((r["memo"] for r in self.store.slot_rows(body.project_uid) if r["path"] == slot), {}))
            deps = [DepDir(d.path, d.kind, dict(d.locks), d.python) for d in body.dep_dirs]
            steps = recipe.plan(slot, deps, memo, body.setup, air_gap=bool(self._meta_read(body.job_id).get("air_gap")))
            meta = await asyncio.to_thread(self._meta, body.job_id)
            result = await recipe.run(steps, meta / "setup.log")
            memo.update(result.memo)
            self._memo[body.job_id] = memo
            if not result.ok:
                raise JobError("setup_failed", f"setup step {(result.failed_step or 0) + 1} failed (see the setup log on that computer)")
            cwd = os.path.realpath(os.path.join(slot, body.scope))
            if os.path.commonpath([cwd, os.path.realpath(slot)]) != os.path.realpath(slot):
                raise JobError("bad_scope", "the scope leaves the job folder", 422)
            if body.agent is not None:
                await self.agent.launch(caller, body, slot, cwd)
                host_admit.runner_started(body.job_id)
                return
            command = _replace_roots(body.command or "", body.caller_roots, os.path.realpath(slot))

            def launch() -> None:
                runner.start(body.job_id, cwd=cwd, command=command, env=body.env, time_cap_s=body.time_cap_s, meta_dir=meta, socket=self.socket)
                started["session"] = True

            await _uninterruptible(launch)
            self.store.host_set(body.job_id, state=HostState.RUNNING, started_at=self._clock())
            host_admit.runner_started(body.job_id)
        except asyncio.CancelledError:
            if started["session"]:
                await asyncio.to_thread(runner.stop, body.job_id, meta_dir=self._meta(body.job_id), socket=self.socket)
            await self.agent.abandon(body.job_id)
            self._free_job_slots(body.job_id, body.project_uid)
            raise
        except Exception as exc:  # noqa: BLE001
            detail = exc.detail if isinstance(exc, JobError) else f"preparing the job failed ({type(exc).__name__})"
            log.warning("pack_job_host_prepare_failed", job_id=body.job_id, error=type(exc).__name__, detail=detail)
            self._free_job_slots(body.job_id, body.project_uid)
            self.store.host_set(body.job_id, state=HostState.FAILED, detail=detail, ended_at=self._clock())

    async def status(self, caller: str, body: JobIdBody) -> Dict[str, Any]:
        def run() -> StatusAnswer:
            row, _ = self._gated_row(caller, body.job_id)
            if row.body == "agent":
                return self.agent.status(row)
            if row.state in (HostState.PREPARING, HostState.FAILED, HostState.STOPPED, HostState.MISSING):
                return StatusAnswer(state=row.state, exit_code=row.exit_code, detail=row.detail)
            if not (self.jobs_root / "meta" / body.job_id).exists():
                return StatusAnswer(state=row.state, exit_code=row.exit_code, detail=row.detail)
            live = runner.status(body.job_id, meta_dir=self._meta(body.job_id), socket=self.socket)
            if row.state == HostState.RUNNING and live.state == HostState.EXITED:
                self.store.host_set(body.job_id, state=HostState.EXITED, exit_code=live.exit_code, ended_at=self._clock())
            elif row.state == HostState.RUNNING and live.state == HostState.FAILED:
                self.store.host_set(body.job_id, state=HostState.FAILED, detail=live.detail, ended_at=self._clock())
                self._free_job_slots(body.job_id, row.project_uid)
            return StatusAnswer(state=live.state if row.state == HostState.RUNNING else row.state,
                                exit_code=live.exit_code if live.exit_code is not None else row.exit_code,
                                detail=live.detail or row.detail, output_tail=live.output_tail, output_bytes=live.output_bytes)

        await self.agent.ensure_watch(body.job_id)
        return (await asyncio.to_thread(run)).model_dump(mode="json")

    async def collect(self, caller: str, body: JobIdBody) -> Dict[str, Any]:
        def prepare() -> "tuple[HostJob, Dict[str, Any]]":
            row, _ = self._gated_row(caller, body.job_id)
            if row.state != HostState.EXITED:
                raise JobError("still_running", "the job has not finished", 409)
            meta = self._meta_read(body.job_id)
            if row.result_commit is None:
                got = collect.collect(row.slot_path or "", row.snapshot_commit or "", meta.get("outputs", []), body.job_id,
                                      self._meta(body.job_id) / "out", exclude=[*meta.get("deps", []), *([TASK_EXCLUDE] if row.body == "agent" else [])])
                blob_id = blobs.new_id() if got.bundle_path else None
                meta["changed"] = got.changed
                self._meta_write(body.job_id, meta)
                row = self.store.host_set(body.job_id, result_commit=got.result_commit, result_blob_id=blob_id)
            return row, meta

        row, meta = await asyncio.to_thread(prepare)
        if row.result_blob_id:
            bundle = str(self._meta(body.job_id) / "out" / f"{body.job_id}-result.bundle")
            try:
                await blobs.send_file(self._request_for(caller), bundle, blob_id=row.result_blob_id, kind="bundle")
            except blobs.BlobError as exc:
                raise JobError(exc.code, "the result could not be sent to the other computer", 502) from exc
            except (asyncio.TimeoutError, OSError) as exc:
                raise JobError("unreachable", "the other computer did not take the result", 502) from exc
        return self.agent.decorate(row, CollectAnswer(result_commit=row.result_commit or "", blob_id=row.result_blob_id,
                                                      changed=int(meta.get("changed") or 0))).model_dump(mode="json")

    async def stop(self, caller: str, body: StopBody) -> Dict[str, Any]:
        def run() -> None:
            row, _ = self._gated_row(caller, body.job_id)
            if row.state in (HostState.STOPPED, HostState.FAILED):
                return
            runner.stop(body.job_id, meta_dir=self._meta(body.job_id), socket=self.socket)
            now = self._clock()
            keep = now + KEEP_HOURS * 3600 if body.keep_files else None
            self.store.host_set(body.job_id, state=HostState.STOPPED, ended_at=now, keep_until=keep)
            self._free_job_slots(body.job_id, row.project_uid, keep_hours=KEEP_HOURS if body.keep_files else 0, now=now)

        await asyncio.to_thread(self._gated_row, caller, body.job_id)
        task = self._tasks.get(body.job_id)
        if task is not None:
            task.cancel()
            await asyncio.wait({task}, timeout=STOP_WAIT_S)
        await self.agent.stop_worker_of(body.job_id)
        await asyncio.to_thread(run)
        return {"ok": True}

    async def reply(self, caller: str, body: ReplyBody) -> Dict[str, Any]:
        return await self.agent.reply(caller, body)

    async def release(self, caller: str, body: JobIdBody) -> Dict[str, Any]:
        def run() -> None:
            row, project = self._gated_row(caller, body.job_id)
            if row.state in (HostState.PREPARING, HostState.RUNNING, HostState.PARKED):
                raise JobError("still_running", "stop the job before releasing it", 409)
            now = self._clock()
            self._free_job_slots(body.job_id, row.project_uid, now=now)
            shutil.rmtree(self.jobs_root / "meta" / body.job_id, ignore_errors=True)
            collect.drop_refs(project["root"], body.job_id)
            self.store.host_set(body.job_id, ended_at=row.ended_at or now)

        await asyncio.to_thread(run)
        return {"ok": True}


    def recover(self) -> int:
        rows = self.store.host_list([HostState.PREPARING])
        for row in rows:
            self.store.host_set(row.job_id, state=HostState.FAILED, detail="the server restarted during setup", ended_at=self._clock())
        self._free_orphan_slots(self._clock())
        return len(rows)

    async def recover_agents(self) -> int:
        return await self.agent.recover()

    def _project_root(self, project_uid: str) -> Optional[str]:
        with closing(self._open_db()) as conn:
            row = conn.execute("SELECT root FROM projects WHERE uid = ?", (project_uid,)).fetchone()
        return row["root"] if row else None

    def _reconcile_stale(self, row: HostJob, now: float) -> None:
        live = runner.status(row.job_id, meta_dir=self._meta(row.job_id), socket=self.socket)
        if live.state == HostState.EXITED:
            self.store.host_set(row.job_id, state=HostState.EXITED, exit_code=live.exit_code, ended_at=now)
            return
        runner.stop(row.job_id, meta_dir=self._meta(row.job_id), socket=self.socket)
        self.store.host_set(row.job_id, state=HostState.FAILED, detail="the job ran past its time cap and nobody was asking", ended_at=now)
        self._free_job_slots(row.job_id, row.project_uid, now=now)

    def sweep(self, now: float) -> None:
        folders.sweep(self.store, now=now)
        for row in self.store.host_list():
            if row.state == HostState.RUNNING and row.body != "agent" and row.ended_at is None and row.started_at and now - row.started_at > row.time_cap_s + STALE_RUN_GRACE_S:
                self._reconcile_stale(row, now)
            elif row.state == HostState.EXITED and row.result_commit and row.ended_at and now - row.ended_at > COLLECTED_HOLD_S:
                self._free_job_slots(row.job_id, row.project_uid, now=now)
            if row.ended_at is None or now - row.ended_at <= PURGE_AFTER_S:
                continue
            self._free_job_slots(row.job_id, row.project_uid, now=now)
            shutil.rmtree(self.jobs_root / "meta" / row.job_id, ignore_errors=True)
            root = self._project_root(row.project_uid)
            if root and os.path.isdir(root):
                try:
                    collect.drop_refs(root, row.job_id)
                except JobError as exc:
                    log.info("pack_job_refs_not_dropped", job_id=row.job_id, code=exc.code)
            self.store.host_delete(row.job_id)
        self._free_orphan_slots(now)
