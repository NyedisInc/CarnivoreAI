
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Coroutine, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.pack.jobs import (carry, engine_agent, install as install_mod, engine_run, gitio, load_store, locality, member_link, member_view, needs_model, needs_policy, paths, place, policy as policy_mod, precheck_learn, side_repo, slot_lookup, snapshot,
                                target)
from src.core.pack.jobs.host import default_restrictions
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_NEEDS, TERMINAL, AdmitBody, JobError, JobRecord, JobRequest, JobState, PlaceAnswer
from src.core.pack.machines import capabilities
from src.core.pack.machines.restrictions import Restrictions, scopes_for
from src.core.pack.placement import workload

log = structlog.get_logger(__name__)

ADMIT_TIMEOUT_S = 5.0
APPROVAL_MAX_AGE_S = 24 * 3600
CLASH_REF_KEEP_S = 24 * 3600
SIDE_KEEP_S = 24 * 3600
JOB_KEEP_S = 7 * 24 * 3600
CarryFn = Callable[[str, str, str], Awaitable[Optional[Dict[str, Any]]]]


def idem_key(req: JobRequest) -> str:
    raw = json.dumps([req.caller_session or "", req.command, req.folder, req.kind, sorted(req.outputs), req.time_cap_s,
                      *engine_agent.idem_extra(req), *(["needs", sorted(req.needs), sorted(req.prefer)] if req.needs or req.prefer else [])])
    return hashlib.sha256(raw.encode()).hexdigest()


class Engine(engine_run.RunMixin, engine_agent.AgentMixin):

    def __init__(self, *, state_dir: Path, jobs_root: Path, install_id: str, store: Optional[JobStore] = None,
                 open_db: Optional[Callable[[], sqlite3.Connection]] = None,
                 view_for: Callable[[str, str], place.PlaceView] = place.live_view,
                 target_for: Callable[[str], target.Target] = target.target_for,
                 spawn: Callable[[Coroutine[Any, Any, None]], "asyncio.Task[None]"] = asyncio.ensure_future,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 lost_after_s: float = 90.0, restrictions: Callable[[], Restrictions] = default_restrictions,
                 carry_commits: CarryFn = carry.default_carry, mono: Optional[Callable[[], float]] = None,
                 facts_for: Optional[engine_agent.FactsFn] = None, notifier: Optional[engine_agent.NotifierFn] = None,
                 members: Optional[member_view.MemberView] = None) -> None:
        from src.core.db import connect, db_path_for

        self.state_dir, self.jobs_root, self.install_id = Path(state_dir), Path(jobs_root), install_id
        self.store = store or JobStore(self.state_dir)
        self._open_db = open_db or (lambda: connect(db_path_for(self.state_dir), create=False))
        self._view_for, self._target_for, self._spawn, self._clock, self._sleep = view_for, target_for, spawn, clock, sleep
        self._lost_after_s, self._restrictions, self._carry = lost_after_s, restrictions, carry_commits
        self._tasks: Dict[str, "asyncio.Task[None]"] = {}
        self._last: Dict[str, float] = {}
        self._mono: Callable[[], float] = mono or (time.monotonic if clock is time.time else clock)
        self._locks: Dict[str, list] = {}
        self._cap_lock = threading.Lock()
        self._members = members or member_view.MemberView()
        self._agent_init(facts_for, notifier)

    @asynccontextmanager
    async def _key_lock(self, key: str) -> AsyncIterator[None]:
        entry = self._locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._locks.pop(key, None)

    async def _carry_commits(self, project_root: str, project_uid: str, peer_install_id: str) -> None:
        if member_link.on() and not target.is_ssh(peer_install_id):
            await member_link.connect_for(peer_install_id)
        began = self._mono()
        while True:
            result = await self._carry(project_root, project_uid, peer_install_id)
            error = result.get("error") if isinstance(result, dict) else None
            if error != "member_list_unreadable" or not member_link.on() or target.is_ssh(peer_install_id) or self._mono() - began >= self._lost_after_s:
                break
            await self._sleep(engine_run.POLL_SLOW_S)
        if error:
            raise JobError(str(error), "the other computer could not take the project's commits first", 502)


    def get(self, job_id: str) -> Optional[JobRecord]:
        return self.store.get_job(job_id)

    def list(self, *, limit: int = 50, project_uid: Optional[str] = None, live_only: bool = False) -> List[JobRecord]:
        return self.store.list_jobs(limit=limit, project_uid=project_uid, live_only=live_only)

    async def wait(self, job_id: str, timeout_s: float) -> JobRecord:
        deadline = self._clock() + timeout_s
        self.waiter_enter(job_id)
        try:
            while True:
                rec = self.store.get_job(job_id)
                if rec is None:
                    raise JobError("unknown_job", "no such job", 404)
                if rec.state in TERMINAL or rec.state == JobState.QUESTION or self._clock() >= deadline:
                    return rec
                await self._sleep(0.25)
        finally:
            self.waiter_leave(job_id)


    @staticmethod
    def _git_info_fast(real_dir: str) -> Tuple[Optional[str], Optional[str]]:
        if not os.path.isdir(real_dir):
            return None, None
        cur = real_dir
        while True:
            dotgit = os.path.join(cur, ".git")
            if os.path.isdir(dotgit):
                if os.path.isfile(os.path.join(dotgit, "HEAD")):
                    return cur, os.path.realpath(dotgit)
            elif os.path.isfile(dotgit):
                try:
                    first = Path(dotgit).read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
                except (OSError, IndexError):
                    first = ""
                if first.lower().startswith("gitdir:"):
                    raw_gd = first.split(":", 1)[1].strip()
                    gd = raw_gd if os.path.isabs(raw_gd) else os.path.join(cur, raw_gd)
                    gd_real = os.path.realpath(gd)
                    common_file = os.path.join(gd_real, "commondir")
                    if os.path.isfile(common_file):
                        try:
                            rel = Path(common_file).read_text(encoding="utf-8", errors="replace").strip()
                            common = rel if os.path.isabs(rel) else os.path.join(gd_real, rel)
                            return cur, os.path.realpath(common)
                        except OSError:
                            pass
                    return cur, gd_real
            parent = os.path.dirname(cur)
            if parent == cur:
                return None, None
            cur = parent

    def _cached_git_info(self, folder: str) -> Tuple[Optional[str], Optional[str]]:
        cache = getattr(self, "_git_info_cache", None)
        if cache is None:
            cache = {}
            self._git_info_cache = cache
            self._git_info_lock = threading.Lock()
        real = os.path.realpath(folder)
        now = time.monotonic()
        with self._git_info_lock:
            hit = cache.get(real)
            if hit is not None and now < hit[2]:
                return hit[0], hit[1]
        top, common = self._git_info_fast(real)
        if top is None and os.path.isdir(real):
            cp = gitio.run(["rev-parse", "--show-toplevel"], cwd=real, check=False, quiet_fail=True)
            if cp.returncode == 0:
                top = os.path.realpath(gitio.out(cp))
                c_cp = gitio.run(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=real, check=False, quiet_fail=True)
                common = os.path.realpath(gitio.out(c_cp)) if c_cp.returncode == 0 else None
        with self._git_info_lock:
            if len(cache) > 512:
                cache.clear()
            cache[real] = (top, common, now + 60.0)
        return top, common

    def _resolve_project(self, folder: str) -> Tuple[Optional[Dict[str, str]], str]:
        real = os.path.realpath(folder)
        top, common = self._cached_git_info(real)
        if top is None:
            return None, "the folder is not inside a git work tree"
        with closing(self._open_db()) as conn:
            rows = [dict(r) for r in conn.execute("SELECT uid, root, display_name FROM projects WHERE host_key = 'local' "
                                                  "AND pack_state != 'moved_away' AND archived_at IS NULL")]
        under = [r for r in rows if real == os.path.realpath(r["root"]) or real.startswith(os.path.realpath(r["root"]).rstrip("/") + "/")]
        found = max(under, key=lambda r: len(os.path.realpath(r["root"])), default=None)
        if found is None and common is not None:
            for r in rows:
                if not os.path.isdir(r["root"]):
                    continue
                _rtop, rcommon = self._cached_git_info(r["root"])
                if rcommon is not None and rcommon == common:
                    found = r
                    break
        if found is None:
            return None, "the folder is not inside a project carnivore knows"
        if not found["uid"]:
            return None, "the project has no uid yet"
        root_top, _ = self._cached_git_info(found["root"])
        if root_top is None or root_top != os.path.realpath(found["root"]):
            return None, "the project folder is not the top of its git repository"
        return {"uid": found["uid"], "name": found["display_name"], "root": found["root"]}, ""

    def _here(self, job_id: str, key: str, req: JobRequest, uid: str, name: str, reason: str) -> JobRecord:
        now = self._clock()
        return self.store.create_job(JobRecord(id=job_id, idem_key=key, project_uid=uid, project_name=name, caller_session=req.caller_session,
                                               request_json=json.dumps({"request": dataclasses.asdict(req)}), state=JobState.HERE,
                                               reason=reason, created_at=now, updated_at=now, ended_at=now,
                                               **engine_agent.agent_columns(req)))

    def _refused(self, job_id: str, key: str, req: JobRequest, uid: str, name: str, answer: PlaceAnswer, reason: str) -> JobRecord:
        now = self._clock()
        return self.store.create_job(JobRecord(id=job_id, idem_key=key, project_uid=uid, project_name=name, caller_session=req.caller_session,
                                               request_json=json.dumps({"request": dataclasses.asdict(req)}), state=JobState.REFUSED,
                                               reason=reason, error_code=answer.code, error_detail=reason, created_at=now, updated_at=now,
                                               ended_at=now, **engine_agent.agent_columns(req)))

    @staticmethod
    def _roots(folder: str, snap: Any, project_root: str) -> List[str]:
        raw_top = folder[:-len(snap.scope) - 1] if snap.scope and folder.endswith("/" + snap.scope) else folder
        return list(dict.fromkeys([raw_top.rstrip("/") or "/", snap.toplevel, project_root, os.path.realpath(project_root)]))[:4]

    def _snap_ctx(self, req: JobRequest, snap: Any, project_root: str, install: Sequence[str] = (), member: bool = False) -> str:
        return json.dumps({"request": dataclasses.asdict(req), **({"install": list(install)} if install else {}), **({"member": True} if member else {}), "snap": {
            "toplevel": snap.toplevel, "head": snap.head, "scope": snap.scope, "project_root": project_root, "notes": snap.notes,
            "roots": self._roots(req.folder, snap, project_root), "dep_dirs": [dataclasses.asdict(d) for d in snap.dep_dirs]}})


    async def propose(self, req: JobRequest) -> JobRecord:
        req.validate()
        key = idem_key(req)
        async with self._key_lock(key):
            live = self.store.find_live_by_idem(key)
            if live is not None:
                return await self._refresh(live) if live.state == JobState.WAITING_APPROVAL else live
            return await self._propose(req, key)

    async def _admit(self, answer: PlaceAnswer, job_id: str, uid: str, req: JobRequest, hard: Optional[List[str]] = None) -> None:
        peer = self._target_for(answer.peer_install_id or "")
        body = AdmitBody(job_id=job_id, project_uid=uid, kind=req.kind, est_cpu=req.est_cpu, est_ram_gb=req.est_ram_gb,
                         needs=hard or None, **engine_agent.admit_fields(req))
        try:
            await asyncio.wait_for(peer.admit(body), ADMIT_TIMEOUT_S + 1)
        except asyncio.TimeoutError as exc:
            raise JobError("unreachable", f"{answer.peer_label} was too slow to answer", 502) from exc

    async def _propose(self, req: JobRequest, key: str) -> JobRecord:
        job_id = paths.new_job_id()
        if capabilities.mesh_on() and slot_lookup.is_within(os.path.realpath(req.folder), os.path.realpath(str(self.jobs_root))):
            return self._here(job_id, key, req, "", "", member_view.NO_CHAIN)
        if isinstance(req, engine_agent.AgentRequest):
            await self._agent_prepare(req)
        project, why = await asyncio.to_thread(self._resolve_project, req.folder)
        if project is None:
            return self._here(job_id, key, req, "", "", why)
        uid, name, root = project["uid"], project["name"], project["root"]
        pol = policy_mod.get(self.store, uid)
        is_agent = isinstance(req, engine_agent.AgentRequest)
        if not is_agent:
            local_why = locality.local_only_reason(req.command, req.folder, root, local_only_globs=pol.local_only)
            if local_why:
                load_store.record_guard_event(self.store, "local_only_path")
                return self._here(job_id, key, req, uid, name, local_why)
        command_shape = None if is_agent else precheck_learn.shape(req.command)
        if command_shape and load_store.shape_override_get(self.store, uid, command_shape) == "local_only":
            return self._here(job_id, key, req, uid, name, f"shape {command_shape} is pinned local-only by the owner")
        prof = precheck_learn.profile(self.store, uid, command_shape) if command_shape else None
        effective_kind = workload.KIND_AGENT if (is_agent and req.kind == "suite") else (
            workload.classify_command(req.command, requested_kind=req.kind) if not is_agent else req.kind)
        tag: Dict[str, Any] = {"kind": effective_kind}
        if prof is not None and req.est_cpu is None and prof.p75_cpu_cores is not None:
            tag["est_cpu_cores"] = prof.p75_cpu_cores
        if prof is not None and req.est_ram_gb is None and prof.p75_ram_gb is not None:
            tag["est_ram_gb"] = prof.p75_ram_gb
        for field, tag_key in (("est_cpu", "est_cpu_cores"), ("est_ram_gb", "est_ram_gb")):
            if getattr(req, field) is not None:
                tag[tag_key] = getattr(req, field)
        try:
            work = workload.resolve(tag)
        except ValueError as exc:
            raise JobError("bad_request", str(exc), 422) from exc
        est_rt = prof.p50_wall_s if prof is not None else workload.est_runtime_s(work.kind)
        try:
            view = await asyncio.to_thread(self._view_for, root, uid)
        except JobError as exc:
            if exc.code != "pack_not_running":
                raise
            return self._here(job_id, key, req, uid, name, exc.detail)
        view = dataclasses.replace(view, peer_overheads=load_store.peer_overheads(self.store, uid))
        no_upload = False
        if capabilities.mesh_on() and pol.auto_delegate:
            view = await self._members.extend(view, root, uid, store=self.store, self_iid=self.install_id)
            view, no_upload = member_view.without_refused_uploads(view, scopes_for(self._restrictions(), tracks_master=False))
        if is_agent:
            view = self._agent_view(view, family=(req.launch or {}).get("family"))
        setup_needs = await asyncio.to_thread(self._setup_needs, uid, req.folder, root, pol)
        asks = await asyncio.to_thread(needs_policy.merge, self.store, uid, req, setup_needs)
        ask: Dict[str, Any] = {k: v for k, v in (("needs", asks.strict), ("filters", asks.filters), ("prefer", asks.prefer)) if v}
        answer = place.place(work, uid, pol, view, est_runtime_s=est_rt, **ask)
        answer = await needs_model.refine(answer, work, uid, pol, view, ask, req.kind, req.command or "")
        if answer.decision == "remote" and not target.is_ssh(answer.peer_install_id or "") \
                and not scopes_for(self._restrictions(), tracks_master=False) & {"replica", "migrate"}:
            answer = PlaceAnswer("here", None, None, "this computer's own settings accept no uploads, so a result could not come back")
        elif no_upload and answer.decision == "here" and "no other computer" in answer.reason:
            answer = PlaceAnswer("here", None, None, "this computer's own settings accept no uploads from a member, so a result could not come back")
        refused: List[str] = []
        for _ in range(2):
            if answer.decision != "remote":
                break
            try:
                await self._admit(answer, job_id, uid, req,
                                  [w for w in asks.hard if w not in install_mod.covered(answer.install) and not w.startswith("label:")]
                                  if capabilities.has(view.caps.get(answer.peer_install_id or ""), CAP_NEEDS) else None)
                break
            except JobError as exc:
                refused.append(f"{answer.peer_label} {exc.detail}")
                pol = dataclasses.replace(pol, never_use=[*pol.never_use, answer.peer_install_id or ""])
                answer = place.place(work, uid, pol, view, **ask)
        else:
            if answer.decision == "remote":
                answer = PlaceAnswer("here", None, None, "no other computer could take it")
        reason = answer.reason + (f" ({'; '.join(refused)})" if refused and answer.decision != "remote" else "")
        if answer.decision == "refused":
            return self._refused(job_id, key, req, uid, name, answer, reason)
        if answer.decision != "remote":
            return self._here(job_id, key, req, uid, name, reason)
        try:
            snap = await asyncio.to_thread(snapshot.take, req.folder, uid, job_id, jobs_root=self.jobs_root, carry=pol.carry,
                                           clock=self._clock, project_root=root, agent=isinstance(req, engine_agent.AgentRequest), commit_ref=req.commit)
        except JobError as exc:
            if exc.code not in ("snapshot_too_large", "harness_linked"):
                raise
            return self._here(job_id, key, req, uid, name, exc.detail)
        now = self._clock()
        peer_id = answer.peer_install_id or ""
        member = peer_id in view.mesh_members
        rec = JobRecord(
            id=job_id, idem_key=key, project_uid=uid, project_name=name, caller_session=req.caller_session,
            request_json=self._snap_ctx(req, snap, root, answer.install, member),
            state=JobState.WAITING_APPROVAL, peer_install_id=answer.peer_install_id,
            peer_label=answer.peer_label, reason=reason, scope=snap.scope, snapshot_commit=snap.commit, snapshot_tree=snap.tree,
            snapshot_at=snap.taken_at, created_at=now, updated_at=now, **engine_agent.agent_columns(req))
        if not member:
            return self.store.create_job(rec)
        with self._cap_lock:
            held = sum(1 for r in self.store.list_jobs(limit=500, live_only=True) if r.peer_install_id == peer_id)
            if held >= member_view.MAX_JOBS_PER_MEMBER:
                return self._here(job_id, key, req, uid, name, f"{answer.peer_label} already holds {member_view.MAX_JOBS_PER_MEMBER} jobs from this computer")
            return self.store.create_job(rec)

    async def _refresh(self, rec: JobRecord) -> JobRecord:
        ctx = engine_run.load_ctx(rec)
        req, root = engine_run.request_of(ctx), ctx["snap"]["project_root"]
        pol = policy_mod.get(self.store, rec.project_uid)
        try:
            snap = await asyncio.to_thread(snapshot.take, req.folder, rec.project_uid, rec.id, jobs_root=self.jobs_root, carry=pol.carry,
                                           clock=self._clock, project_root=root, agent=isinstance(req, engine_agent.AgentRequest), commit_ref=req.commit)
        except JobError as exc:
            if exc.code == "harness_linked":
                self.cancel(rec.id, exc.detail)
                return self.store.get_job(rec.id) or rec
            log.info("pack_job_refresh_skipped", job_id=rec.id, code=exc.code)
            return rec
        try:
            return self.store.set_state(rec.id, JobState.WAITING_APPROVAL, note="fresh snapshot", request_json=self._snap_ctx(req, snap, root, ctx.get("install") or (), bool(ctx.get("member"))),
                                        scope=snap.scope, snapshot_commit=snap.commit, snapshot_tree=snap.tree, snapshot_at=snap.taken_at)
        except JobError as exc:
            if exc.code != "job_ended":
                raise
            return self.store.get_job(rec.id) or rec


    async def proceed(self, job_id: str) -> JobRecord:
        rec = self.store.get_job(job_id)
        if rec is None:
            raise JobError("unknown_job", "no such job", 404)
        async with self._key_lock(rec.idem_key):
            rec = self.store.get_job(job_id) or rec
            if rec.state != JobState.WAITING_APPROVAL:
                return rec
            try:
                rec = self.store.set_state(job_id, JobState.MIRRORING, note="approved", started_at=self._clock())
            except JobError as exc:
                if exc.code != "job_ended":
                    raise
                return self.store.get_job(job_id) or rec
            self._start_task(job_id)
            return rec

    async def submit(self, req: JobRequest) -> JobRecord:
        rec = await self.propose(req)
        return await self.proceed(rec.id) if rec.state == JobState.WAITING_APPROVAL else rec

    def cancel(self, job_id: str, reason: str = "denied") -> None:
        rec = self.store.get_job(job_id)
        if rec is None or rec.state != JobState.WAITING_APPROVAL:
            return
        self._end(job_id, JobState.STOPPED, code="cancelled", detail=reason)
        side_repo.drop_ref(str(paths.side_repo_dir(self.jobs_root, rec.project_uid)), f"refs/heads/job-{job_id}")

    async def stop(self, job_id: str) -> JobRecord:
        rec = self.store.get_job(job_id)
        if rec is None:
            raise JobError("unknown_job", "no such job", 404)
        if rec.state in TERMINAL:
            return rec
        if rec.state == JobState.WAITING_APPROVAL:
            self.cancel(job_id, "stopped")
            return self.store.get_job(job_id) or rec
        if rec.state == JobState.LANDING:
            return rec
        task = self._tasks.get(job_id)
        if task is not None:
            task.cancel()
        peer_id = rec.peer_install_id or ""
        try:
            peer = self._target_for(peer_id)
            await asyncio.wait_for(peer.stop(job_id, False), 12)
        except (JobError, asyncio.TimeoutError) as exc:
            if isinstance(exc, JobError) and exc.code == "unknown_job":
                log.info("pack_job_stop_host_answer", job_id=job_id, code=exc.code)
            else:
                self._end(job_id, JobState.LOST, code="unreachable", detail="stop was sent but the other computer did not answer or refused it")
                return self.store.get_job(job_id) or rec
        self._end(job_id, JobState.STOPPED, code="stopped", detail="stopped by the asker")
        try:
            await asyncio.wait_for(self._target_for(peer_id).release(job_id), 5)
        except (JobError, asyncio.TimeoutError):
            log.info("pack_job_release_skipped", job_id=job_id)
        return self.store.get_job(job_id) or rec


    async def recover(self) -> int:
        count = 0
        for rec in self.store.list_jobs(limit=500, live_only=True):
            if rec.state == JobState.WAITING_APPROVAL:
                continue
            if rec.state == JobState.PLACING:
                self._end(rec.id, JobState.FAILED, code="restarted", detail="the server restarted while placing")
                continue
            self._start_task(rec.id)
            count += 1
        return count

    def _sweep_sync(self, now: float) -> List[JobRecord]:
        rows = self.store.sweep_rows()
        for rec in rows:
            if rec.state == JobState.WAITING_APPROVAL and now - rec.created_at > APPROVAL_MAX_AGE_S:
                self._end(rec.id, JobState.FAILED, code="approval_expired", detail="approval never came")
                side_repo.drop_ref(str(paths.side_repo_dir(self.jobs_root, rec.project_uid)), f"refs/heads/job-{rec.id}")
            elif rec.state == JobState.DONE and rec.land_json and rec.ended_at and now - rec.ended_at > CLASH_REF_KEEP_S:
                ctx = engine_run.load_ctx(rec)
                if json.loads(rec.land_json).get("clashes") and ctx.get("snap"):
                    gitio.run(["update-ref", "-d", f"refs/carnivore/jobs/{rec.id}"], cwd=ctx["snap"]["toplevel"], check=False)
        self.store.purge_before(now - JOB_KEEP_S)
        live = {r.id for r in self.store.list_jobs(limit=500, live_only=True)}
        keep = {f"refs/heads/{p}-{i}" for i in live for p in ("job", "result")}
        repos = self.jobs_root / "repos"
        for side in sorted(repos.glob("*.git")) if repos.is_dir() else []:
            try:
                side_repo.prune(str(side), older_than_s=SIDE_KEEP_S, keep=keep, now=now)
            except JobError as exc:
                log.warning("pack_job_prune_failed", side=side.name, code=exc.code)
        return [r for r in rows if r.state == JobState.LOST and r.ended_at and now - r.ended_at < APPROVAL_MAX_AGE_S]

    async def sweep(self) -> None:
        for rec in await asyncio.to_thread(self._sweep_sync, self._clock()):
            try:
                await asyncio.wait_for(self._target_for(rec.peer_install_id or "").stop(rec.id, True), 10)
            except (JobError, asyncio.TimeoutError):
                continue
            log.info("pack_job_lost_stopped", job_id=rec.id)
