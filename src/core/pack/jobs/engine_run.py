
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import posixpath
import re
from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

import structlog

from src.core.pack.jobs import bundle_io, engine_agent, gitio, install as install_mod, land, load_store, member_link, needs_policy, paths, policy as policy_mod, precheck_learn, snapshot, target
from src.core.pack.placement.needs import Need
from src.core.pack.relay import member_reach
from src.core.pack.jobs.types import (AdmitBody, DepDirWire, JobError, JobRecord, JobRequest, JobState, LandResult, HostState, StartBody)

log = structlog.get_logger(__name__)
T = TypeVar("T")

CARRY_OVER_COMMITS = 50
INSTALL_POLL_S, INSTALL_NOTE_S = 5.0, 30.0
HOST_REFUSALS = {"host_busy", "no_free_slot", "pack_restricted", "project_not_here", "not_a_counterpart", "no_harness", "account_not_usable",
                 "lacks_tool", "pegged", "install_failed", "install_limit", "no_brew", "tool_not_allowed"}
INSTALL_GRACE_S = 120.0
INSTALL_ID = re.compile(r"ins_[0-9a-f]{12}")
INSTALL_STATES = ("queued", "running", "done", "failed")
MESH_REFUSALS = {"mesh_power_refused"}
COLLECT_WAIT_S, COLLECT_RETRY_S = 20 * 3600, 60.0
POLL_FAST_S, POLL_SLOW_S, POLL_FAST_FOR_S = engine_agent.POLL_FAST_S, engine_agent.POLL_SLOW_S, engine_agent.POLL_FAST_FOR_S


class Lost(Exception):
    pass


def load_ctx(rec: JobRecord) -> Dict[str, Any]:
    return json.loads(rec.request_json or "{}")


def request_of(ctx: Dict[str, Any]) -> JobRequest:
    return (engine_agent.AgentRequest if "task" in ctx["request"] else JobRequest)(**ctx["request"])


def outputs_of(req: JobRequest, pol: policy_mod.Policy, scope: str = "") -> List[str]:
    asked = [posixpath.join(scope, o) if scope else o for o in req.outputs]
    return list(dict.fromkeys([*asked, *pol.bring_back]))[:100]


class RunMixin:


    def _start_task(self, job_id: str) -> None:
        task = self._spawn(self._run(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda t, j=job_id: self._tasks.pop(j, None))

    def _end(self, job_id: str, state: JobState, *, code: Optional[str] = None, detail: Optional[str] = None, **fields: Any) -> None:
        try:
            if code:
                fields.update(error_code=code, error_detail=detail)
            self.store.set_state(job_id, state, note=detail or state.value, **fields)
        except JobError as exc:
            if exc.code != "job_ended":
                raise
            return
        if state in engine_agent.NOTIFY_STATES:
            self._notify_soon(job_id, state.value)

    async def _run(self, job_id: str) -> None:
        self._last[job_id] = self._mono()
        keep = None
        try:
            rec = self.store.get_job(job_id)
            keep = member_link.hold(rec.peer_install_id) if rec is not None and rec.peer_install_id else None
            if rec is not None and rec.state in (JobState.MIRRORING, JobState.STARTING):
                await self._mirror_start(rec)
                rec = self.store.get_job(job_id)
            if rec is not None and rec.state in (JobState.STARTING, JobState.RUNNING, JobState.QUESTION):
                if not await self._poll_member_aware(rec):
                    return
                rec = self.store.get_job(job_id)
            if rec is not None and rec.state in (JobState.COLLECTING, JobState.LANDING):
                await self._collect_land(rec)
        except asyncio.CancelledError:
            raise
        except Lost:
            self._end(job_id, JobState.LOST, code="lost", detail="the other computer stopped answering")
        except JobError as exc:
            row = self.store.get_job(job_id)
            if (exc.code in HOST_REFUSALS or (exc.code in MESH_REFUSALS and member_link.on())) and row is not None \
                    and row.state in (JobState.MIRRORING, JobState.STARTING):
                self._end(job_id, JobState.HERE, code=exc.code, detail=f"{row.peer_label or 'the other computer'} {exc.detail}")
            elif exc.code != "job_ended":
                self._end(job_id, JobState.FAILED, code=exc.code, detail=exc.detail)
        except Exception as exc:  # noqa: BLE001
            log.warning("pack_job_run_failed", job_id=job_id, error=type(exc).__name__)
            self._end(job_id, JobState.FAILED, code="internal", detail=f"the job failed ({type(exc).__name__})")
        finally:
            self._last.pop(job_id, None)
            if keep is not None:
                keep.cancel()

    async def _peer(self, job_id: str, peer_id: str, call: Callable[[Any], Awaitable[T]]) -> T:
        while True:
            try:
                out = await call(self._target_for(peer_id))
            except JobError as exc:
                if exc.code != "unreachable":
                    raise
                if self._mono() - self._last.get(job_id, self._mono()) > self._lost_after_s:
                    raise Lost() from exc
                await self._sleep(POLL_SLOW_S)
                continue
            self._last[job_id] = self._mono()
            return out


    def _behind(self, side: str, head: str, prerequisites: List[str]) -> int:
        known = [s for s in prerequisites
                 if gitio.run(["cat-file", "-e", f"{s}^{{commit}}"], git_dir=side, check=False).returncode == 0]
        cp = gitio.run(["rev-list", "--count", head, *(["--not", *known] if known else [])], git_dir=side, check=False)
        text = gitio.out(cp)
        return int(text) if cp.returncode == 0 and text.isdigit() else 10 ** 9

    async def _prerequisites(self, uid: str, peer_id: str, *, with_base: bool) -> List[str]:
        tips = await asyncio.to_thread(bundle_io.confirmed_tips, self._open_db, uid, peer_id)
        base = self.store.base_get(uid, peer_id) if with_base else None
        return [*tips, *([base] if base else [])]

    def _air_gap(self, project_uid: str) -> bool:
        with closing(self._open_db()) as conn:
            row = conn.execute("SELECT air_gap FROM projects WHERE uid = ?", (project_uid,)).fetchone()
        return True if row is None else bool(row[0])

    def _setup_needs(self, project_uid: str, folder: str, root: str, pol: Any) -> List[Need]:
        return needs_policy.setup_filters([folder, root], pol.setup, self._air_gap(project_uid))

    def _start_body(self, rec: JobRecord, ctx: Dict[str, Any], blob_id: str, air_gap: bool = False, send_identity: bool = False) -> StartBody:
        req, snap = request_of(ctx), ctx["snap"]
        pol = policy_mod.get(self.store, rec.project_uid)
        deps = [DepDirWire(path=d["path"], kind=d["kind"], locks=d.get("locks", {}), python=d.get("python")) for d in snap["dep_dirs"]]
        agent = engine_agent.agent_spec(req, send_identity)
        return StartBody(job_id=rec.id, project_uid=rec.project_uid, snapshot_commit=rec.snapshot_commit or "", snapshot_blob_id=blob_id,
                         scope=snap["scope"], dep_dirs=deps, command=None if agent else req.command, agent=agent, kind=req.kind, est_cpu=req.est_cpu, est_ram_gb=req.est_ram_gb, env=req.env,
                         outputs=outputs_of(req, pol, snap["scope"]),
                         time_cap_s=req.time_cap_s, caller_roots=snap["roots"], setup=pol.setup, air_gap=air_gap)

    async def _install_first(self, rec: JobRecord, tools: List[str]) -> None:
        peer, label, began = rec.peer_install_id or "", rec.peer_label or "the other computer", self._clock()
        req = request_of(load_ctx(rec))
        await self._peer(rec.id, peer, lambda t: t.admit(AdmitBody(job_id=rec.id, project_uid=rec.project_uid, kind=req.kind, est_cpu=req.est_cpu,
                                                                  est_ram_gb=req.est_ram_gb, **engine_agent.admit_fields(req))))
        rows = await self._peer(rec.id, peer, lambda t: t.install(rec.id, rec.project_uid, tools))
        names = ", ".join(tools)
        noted = -INSTALL_NOTE_S
        for row in rows:
            while True:
                if not INSTALL_ID.fullmatch(str(row.get("id"))) or row.get("state") not in INSTALL_STATES:
                    raise JobError("install_failed", f"{label} answered an install in a form this computer does not accept")
                if row["state"] in ("done", "failed"):
                    break
                if self._clock() - began > install_mod.TIMEOUT_S * len(rows) + INSTALL_GRACE_S:
                    raise JobError("install_failed", f"installing {names} on {label} did not finish in time")
                if self._clock() - began - noted >= INSTALL_NOTE_S:
                    noted = self._clock() - began
                    self.store.set_state(rec.id, rec.state, note=f"installing {names} on {label} with Homebrew, started {int(noted)} s ago")
                await self._sleep(INSTALL_POLL_S)
                row = await self._peer(rec.id, peer, lambda t, i=row["id"]: t.install_status(i))
            if row["state"] == "failed":
                raise JobError("install_failed", f"installing {names} on {label} failed (exit {install_mod.clean_text(row.get('exit_code'))}): "
                                                 f"{install_mod.clean_text(row.get('tail')) or 'no output'}")

    async def _mirror_start(self, rec: JobRecord) -> None:
        ctx, peer, uid = load_ctx(rec), rec.peer_install_id or "", rec.project_uid
        if ctx.get("install"):
            await self._install_first(rec, [str(t) for t in ctx["install"]])
        snap = ctx["snap"]
        side = str(paths.side_repo_dir(self.jobs_root, uid))
        prereq = await self._prerequisites(uid, peer, with_base=True)
        head = snap.get("head")
        if head and (not prereq or await asyncio.to_thread(self._behind, side, head, prereq) > CARRY_OVER_COMMITS):
            await self._carry_commits(snap["project_root"], uid, peer)
            prereq = await self._prerequisites(uid, peer, with_base=True)
        air_gap = await asyncio.to_thread(self._air_gap, uid)
        send_identity = rec.body == "agent" and await self._peer_has(rec, engine_agent.CAP_ACCOUNT_IDENTITY)
        out_dir = self.jobs_root / "outbox"
        out_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(out_dir, 0o700)
        path = out_dir / f"{rec.id}.bundle"
        for attempt in range(3):
            try:
                bundle_bytes = await asyncio.to_thread(bundle_io.make_bundle, side, f"refs/heads/job-{rec.id}", [] if attempt == 2 else prereq, str(path))
                blob_id = await self._peer(rec.id, peer, lambda t: t.send_bundle(str(path)))
                self.store.set_state(rec.id, JobState.STARTING, note=f"bundle sent ({bundle_bytes} B)")
                await self._peer(rec.id, peer, lambda t: t.start(self._start_body(rec, ctx, blob_id, air_gap, send_identity)))
                break
            except JobError as exc:
                if exc.code != "bundle_unverified":
                    raise
                if attempt == 0:
                    self.store.base_clear(uid, peer)
                    await self._carry_commits(snap["project_root"], uid, peer)
                    prereq = await self._prerequisites(uid, peer, with_base=False)
                elif attempt == 2:
                    raise JobError("bundle_unverified", "the other computer could not read the code") from exc
            finally:
                path.unlink(missing_ok=True)
        if head:
            self.store.base_set(uid, peer, head)


    async def _poll(self, rec: JobRecord, on_answer: Optional[Callable[[], None]] = None) -> bool:
        if rec.body == "agent":
            return await self._poll_agent(rec, on_answer)
        began = self._clock()
        while True:
            st = await self._peer(rec.id, rec.peer_install_id or "", lambda t: t.status(rec.id))
            if on_answer is not None:
                on_answer()
            if st.state == HostState.EXITED:
                self.store.set_state(rec.id, JobState.COLLECTING, note="the command finished", exit_code=st.exit_code, output_tail=st.output_tail)
                return True
            if st.state in (HostState.FAILED, HostState.MISSING, HostState.STOPPED):
                end = JobState.STOPPED if st.state == HostState.STOPPED else JobState.FAILED
                self._end(rec.id, end, code=f"host_{st.state.value}", detail=st.detail or f"the job is {st.state.value} on the other computer",
                          exit_code=st.exit_code, output_tail=st.output_tail)
                return False
            if st.state == HostState.RUNNING and rec.state != JobState.RUNNING:
                rec = self.store.set_state(rec.id, JobState.RUNNING, note="running", started_at=self._clock())
            await self._sleep(POLL_FAST_S if self._clock() - began < POLL_FAST_FOR_S else POLL_SLOW_S)


    async def _collect_land(self, rec: JobRecord) -> None:
        ctx, peer, job_id = load_ctx(rec), rec.peer_install_id or "", rec.id
        pol = policy_mod.get(self.store, rec.project_uid)
        side = str(paths.side_repo_dir(self.jobs_root, rec.project_uid))
        try:
            await self._collect_member_aware(rec, ctx, pol, side)
        except JobError as exc:
            if exc.code != "peer_left":
                await self._release_host(job_id, peer)
            raise
        except Exception:
            await self._release_host(job_id, peer)
            raise
        await self._release_host(job_id, peer)
        self._record_job_metrics(job_id, ctx, peer)

    def _record_job_metrics(self, job_id: str, ctx: Dict[str, Any], peer: str) -> None:
        try:
            rec = self.store.get_job(job_id)
            if rec is None or rec.state != JobState.DONE or not peer:
                return
            ev_map: Dict[str, float] = {}
            bundle_bytes = 0
            for e in self.store.events(job_id):
                ev_map.setdefault(str(e["state"]), float(e["at"]))
                note = str(e.get("note") or "")
                if note.startswith("bundle sent (") and note.endswith(" B)"):
                    raw_b = note[len("bundle sent ("):-3]
                    if raw_b.isdigit():
                        bundle_bytes = int(raw_b)
            t_mir, t_st, t_run, t_col = ev_map.get("mirroring"), ev_map.get("starting"), ev_map.get("running"), ev_map.get("collecting")
            t_dn = ev_map.get("done") or rec.ended_at
            if t_mir is not None and t_st is not None and t_col is not None and t_dn is not None:
                mirror_s = max(0.0, t_st - t_mir)
                start_s = max(0.0, (t_run - t_st) if t_run is not None else 0.0)
                run_s = max(0.0, t_col - (t_run if t_run is not None else t_st))
                tail_s = max(0.0, t_dn - t_col)
                overhead_s = mirror_s + start_s + tail_s
                load_store.record_overhead(self.store, rec.project_uid, peer, overhead_s,
                                           mirror_s=mirror_s, bundle_bytes=bundle_bytes, now=t_dn)
                req = request_of(ctx)
                if rec.body != "agent" and req.command:
                    cmd_shape = precheck_learn.shape(req.command)
                    if cmd_shape:
                        precheck_learn.record(self.store, rec.project_uid, cmd_shape, run_s, now=t_dn, source="remote")
        except Exception:  # noqa: BLE001
            pass

    async def _collect_member_aware(self, rec: JobRecord, ctx: Dict[str, Any], pol: policy_mod.Policy, side: str) -> None:
        while True:
            try:
                return await self._collect_and_land(rec, ctx, request_of(ctx), pol, side)
            except Lost:
                row = self.store.get_job(rec.id)
                label = rec.peer_label or "the other computer"
                if not self._member_job(ctx) or row is None or row.state != JobState.COLLECTING \
                        or self._member_wait(row, f"waiting for {label} to come back; its result is kept there"):
                    raise
                await self._sleep(COLLECT_RETRY_S)
                self._last[rec.id] = self._mono()

    async def _poll_member_aware(self, rec: JobRecord) -> bool:
        while True:
            try:
                return await self._poll(rec, self._answered_again(rec) if self._member_job(load_ctx(rec)) else None)
            except Lost:
                row = self.store.get_job(rec.id)
                if not self._member_job(load_ctx(rec)) or row is None or row.state not in (JobState.RUNNING, JobState.QUESTION):
                    raise
                if await self._member_verdict(row) is False:
                    raise JobError("peer_left", f"{row.peer_label or 'the other computer'} was set to one way or left the Pack; its result was not applied")
                if self._member_wait(row, f"waiting for {row.peer_label or 'the other computer'} to come back; the job goes on there"):
                    raise
                await self._sleep(COLLECT_RETRY_S)
                self._last[rec.id] = self._mono()
                rec = self.store.get_job(rec.id) or rec

    def _answered_again(self, rec: JobRecord) -> Callable[[], None]:
        done = [False]

        def run() -> None:
            if done[0]:
                return
            done[0] = True
            events = self.store.events(rec.id)
            row = self.store.get_job(rec.id)
            if row is not None and events and str(events[-1]["note"]).startswith("waiting for "):
                self.store.set_state(rec.id, row.state, note=f"{rec.peer_label or 'the other computer'} answered again")

        return run

    def _member_wait(self, row: JobRecord, text: str) -> bool:
        events = self.store.events(row.id)
        if not events or events[-1]["note"] != text:
            self.store.set_state(row.id, row.state, note=text)
            return False
        return self._clock() - row.updated_at > COLLECT_WAIT_S

    async def _member_verdict(self, rec: JobRecord) -> Optional[bool]:
        ids = await asyncio.to_thread(member_reach.listed_ids_held)
        return None if ids is None else (rec.peer_install_id or "") in ids

    @staticmethod
    def _member_job(ctx: Dict[str, Any]) -> bool:
        return bool(ctx.get("member"))

    async def _check_member(self, rec: JobRecord, ctx: Dict[str, Any]) -> None:
        if not self._member_job(ctx):
            return
        verdict = await self._member_verdict(rec)
        if verdict is False:
            raise JobError("peer_left", f"{rec.peer_label or 'the other computer'} was set to one way or left the Pack; its result was not applied")
        if verdict is None:
            raise Lost()

    async def _release_host(self, job_id: str, peer: str) -> None:
        try:
            await asyncio.wait_for(self._peer(job_id, peer, lambda t: t.release(job_id)), 30)
        except (JobError, Lost, asyncio.TimeoutError) as exc:
            log.info("pack_job_release_skipped", job_id=job_id, error=type(exc).__name__)

    async def _collect_and_land(self, rec: JobRecord, ctx: Dict[str, Any], req: JobRequest, pol: policy_mod.Policy, side: str) -> None:
        job_id, peer, snap = rec.id, rec.peer_install_id or "", ctx["snap"]
        await self._check_member(rec, ctx)
        answer = await self._peer(job_id, peer, lambda t: t.collect(job_id))
        landed = LandResult()
        hostile = target.is_ssh(peer) or self._member_job(ctx)
        if answer.blob_id:
            got = await self._peer(job_id, peer, lambda t: t.fetch_result(job_id, answer, self.state_dir))
            fetched = ""
            try:
                fetched = await asyncio.to_thread(bundle_io.fetch_bundle, side, got, f"refs/carnivore/jobs/{job_id}/result",
                                                  f"refs/heads/result-{job_id}", fsck=hostile)
            finally:
                if fetched or target.is_ssh(peer):
                    bundle_io.consumed(self.state_dir, answer.blob_id)
            if fetched != answer.result_commit or not await asyncio.to_thread(self._is_child_of, side, fetched, rec.snapshot_commit or ""):
                raise JobError("result_mismatch", "the result does not follow from the code that was sent")
            await self._check_member(rec, ctx)
            self.store.set_state(job_id, JobState.LANDING, note=f"{answer.changed} changed", result_commit=fetched)
            async with self._key_lock("land:" + snap["toplevel"]):
                landed = await asyncio.to_thread(land.land, snap["toplevel"], side, rec.snapshot_commit or "", fetched, job_id,
                                                 outputs=outputs_of(req, pol, snap["scope"]), snapshot_at=rec.snapshot_at or 0.0,
                                                 skip=snapshot.harness_paths(snap["scope"]) if isinstance(req, engine_agent.AgentRequest) or hostile else ())
        note = f"done; a change to {', '.join(landed.dropped)} stayed on the worker's computer (harness settings never come back)" if landed.dropped else "done"
        self._end(job_id, JobState.DONE, detail=note, result_commit=answer.result_commit or None, land_json=json.dumps(dataclasses.asdict(landed)),
                  **engine_agent.collect_fields(answer))

    @staticmethod
    def _is_child_of(side: str, commit: str, parent: str) -> bool:
        cp = gitio.run(["rev-list", "--parents", "-n", "1", commit], git_dir=side, check=False)
        return cp.returncode == 0 and gitio.out(cp).split() == [commit, parent]
