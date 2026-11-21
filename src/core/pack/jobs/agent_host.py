
from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog

from src.core.pack.jobs import agent_launch, agent_watch
from src.core.pack.jobs.agent_account import AccountPick, resolve_target_account
from src.core.pack.jobs.agent_types import UsageTotals, digest_of
from src.core.pack.jobs.types import AdmitBody, CollectAnswer, HostJob, HostState, JobError, ReplyBody, StartBody, StatusAnswer
from src.core.pack.machines import probe

log = structlog.get_logger(__name__)

TASK_EXCLUDE = f":(exclude,glob)**/{agent_launch.TASK_DIR}/**"
RESTART_DETAIL = "the server restarted during setup"
GONE_DETAIL = "worker ended while this computer restarted"
_ESCAPE = "\x1b"
_PROFILE_VARS = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME"}
_CLEAR_WAIT_S = 10.0
_PRESENT_WAIT_S = 5.0


def _watcher_observe(app: Any) -> Callable[[str], Any]:
    def observe(session_id: str) -> Any:
        watcher = getattr(app.state, "attention_watcher", None)
        return watcher.observation_for(session_id) if watcher is not None else None

    return observe


@dataclass
class AgentDeps:

    create_worker: Callable[..., Awaitable[agent_launch.WorkerRef]]
    stop_worker: Callable[..., Awaitable[None]]
    observe: Callable[[str], Any]
    send_input: Callable[[str, str], Awaitable[None]]
    listed: Callable[[str], Awaitable[bool]]
    conversation: Callable[[str], Awaitable[Tuple[Optional[str], Optional[str]]]]
    resolve_account: Callable[[str, Optional[str], Optional[str], Optional[str]], AccountPick]
    deliver: Optional[Callable[[str, str], Awaitable[None]]] = None
    present: Optional[Callable[[str], Awaitable[bool]]] = None
    harness_present: Callable[[str], bool] = lambda family: probe.tool_present(family)
    transcript_reader: Callable[..., agent_watch.Read] = agent_watch.read_transcript
    usage_reader: Callable[..., Optional[UsageTotals]] = agent_watch.read_usage_totals
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    poll_s: float = agent_watch.POLL_S

    @classmethod
    def from_app(cls, app: Any) -> "AgentDeps":
        from src.config import settings

        create, stop = agent_launch.worker_hooks(app)

        async def send_input(session_id: str, data: str) -> None:
            await app.state.session_manager.send_input(data, session_id=session_id)

        async def info_of(session_id: str) -> Any:
            return await app.state.session_manager.get_session_info(session_id=session_id)

        async def deliver(session_id: str, text: str) -> None:
            from src.core.sessions import guarded_paste

            try:
                await guarded_paste.paste_through_gates(app.state, session_id, text, guarded_paste.GateOptions(idle_only=True))
            except guarded_paste.PasteRefused as exc:
                raise JobError("worker_not_ready", f"the answer was not typed: {exc.message}", 409) from exc

        async def present(tmux_name: str) -> bool:
            from src.core.tmux_transport.run import tmux_run

            done = await tmux_run(app.state.session_manager.tmux_socket_name(), "has-session", "-t", "=" + tmux_name,
                                  timeout=_PRESENT_WAIT_S)
            return done.returncode != 1

        async def listed(session_id: str) -> bool:
            info = await info_of(session_id)
            return info is not None and bool(info.tmux_session)

        async def conversation(session_id: str) -> Tuple[Optional[str], Optional[str]]:
            info = await info_of(session_id)
            return (info.claude_session_uuid, info.session.working_dir) if info is not None else (None, None)

        return cls(create, stop, _watcher_observe(app), send_input, listed, conversation,
                   lambda family, key, caller, ident: resolve_target_account(family, key, caller, Path(settings.auth_config_file).expanduser(), ident),
                   deliver=deliver, present=present)


class AgentHost:

    def __init__(self, host: Any) -> None:
        self.host = host
        self.deps: Optional[AgentDeps] = None
        self._watches: Dict[str, "asyncio.Task[None]"] = {}
        self._floors: Dict[str, float] = {}
        self._replying: set = set()

    def bind(self, deps: AgentDeps) -> None:
        self.deps = deps

    def _need(self) -> AgentDeps:
        if self.deps is None:
            raise JobError("agent_not_ready", "this computer cannot start an agent job yet", 503)
        return self.deps


    def check(self, caller: str, family: str, account_key: Optional[str], account_identity: Optional[str] = None) -> AccountPick:
        deps = self._need()
        if not deps.harness_present(family):
            raise JobError("no_harness", f"{family} is not installed on this computer", 409)
        return deps.resolve_account(family, account_key, caller, account_identity)

    def row_fields(self, body: StartBody) -> Dict[str, Any]:
        spec = body.agent
        return {"body": "agent", "family": spec.family, "permission_mode": spec.permission_mode} if spec is not None else {}


    async def launch(self, caller: str, body: StartBody, slot: str, cwd: str) -> None:
        deps, spec, job_id = self._need(), body.agent, body.job_id
        jobs_root, real = os.path.realpath(self.host.jobs_root), os.path.realpath(cwd)
        if os.path.commonpath([real, jobs_root]) != jobs_root:
            raise JobError("bad_slot", "the worker's folder is outside this computer's jobs folder", 409)
        pick = await asyncio.to_thread(self.check, caller, spec.family, spec.account_key, spec.account_identity)
        plan = agent_launch.build_launch(spec, Path(real), job_id, pick)
        await asyncio.to_thread(agent_launch.write_task_file, Path(real), spec)
        root = pick.extra_env.get(_PROFILE_VARS[spec.family])
        meta = await asyncio.to_thread(self.host._meta_read, job_id)
        await asyncio.to_thread(self.host._meta_write, job_id, {**meta, "profile_root": root})
        session_id = f"ses_{uuid.uuid4().hex[:8]}"
        self.host.store.host_set(job_id, worker_session_id=session_id, worker_tmux=agent_launch.worker_tmux_name(session_id),
                                 account_label=pick.label, account_how=pick.how)
        label = f"job {job_id[4:12]}" + (f": {spec.agent_type}" if spec.agent_type else "")
        fut = asyncio.ensure_future(deps.create_worker(plan, session_id, label, real))
        try:
            ref = await asyncio.shield(fut)
        except asyncio.CancelledError:
            await asyncio.wait({fut})
            raise
        except Exception as exc:  # noqa: BLE001
            await self._stop_quietly(session_id, None)
            raise self._create_error(exc) from exc
        now = self.host._clock()
        self.host.store.host_set(job_id, worker_session_uuid=ref.session_uuid, worker_tmux=ref.tmux_name, worker_epoch=ref.epoch,
                                 state=HostState.RUNNING, started_at=now)
        self._floors[job_id] = now
        self.start_watch(job_id)

    @staticmethod
    def _create_error(exc: Exception) -> JobError:
        if isinstance(exc, JobError):
            return exc
        status = getattr(exc, "status_code", None)
        return JobError("worker_not_created", f"the worker session could not be created ({status or type(exc).__name__})", 503)

    async def _stop_quietly(self, session_id: str, session_uuid: Optional[str]) -> None:
        try:
            await self._need().stop_worker(session_id, session_uuid)
        except JobError as exc:
            log.warning("pack_jobs_agent_worker_not_stopped", session_id=session_id, code=exc.code)

    def start_watch(self, job_id: str) -> None:
        if job_id in self._watches:
            return
        deps = self._need()
        watch = agent_watch.AgentWatch(
            store=self.host.store, observe=deps.observe, read_result=self._read_result, read_usage=self._read_usage, park=self._park,
            unpark=self._unpark, finish=self.finish, floor=self.floor, busy_replying=lambda j: j in self._replying, clock=self.host._clock,
            sleep=deps.sleep, poll_s=deps.poll_s)
        task = self.host._spawn(watch.run(job_id))
        self._watches[job_id] = task
        task.add_done_callback(lambda t, j=job_id: self._watch_done(j, t))

    def _watch_done(self, job_id: str, task: "asyncio.Task[None]") -> None:
        self._watches.pop(job_id, None)
        if not task.cancelled() and task.exception() is not None:
            log.warning("pack_jobs_agent_watch_failed", job_id=job_id, error=type(task.exception()).__name__)

    def floor(self, job_id: str) -> float:
        row = self.host.store.host_get(job_id)
        return self._floors.get(job_id, ((row.replied_at or row.started_at) if row else None) or 0.0)


    async def _readers(self, row: HostJob) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        deps = self._need()
        conversation, working_dir = await deps.conversation(row.worker_session_id or "")
        meta = await asyncio.to_thread(self.host._meta_read, row.job_id)
        return row.family or "claude", conversation, working_dir, meta.get("profile_root")

    async def _read_result(self, row: HostJob) -> agent_watch.Read:
        return await asyncio.to_thread(self._need().transcript_reader, *await self._readers(row))

    async def _read_usage(self, row: HostJob) -> Optional[UsageTotals]:
        return await asyncio.to_thread(self._need().usage_reader, *await self._readers(row))


    async def _park(self, row: HostJob, qkind: str, text: str) -> None:
        self.host.store.host_set(row.job_id, state=HostState.PARKED, parked_at=self.host._clock(), question=text, question_kind=qkind)

    async def _unpark(self, row: HostJob) -> None:
        self.host.store.host_set(row.job_id, state=HostState.RUNNING, parked_at=None, question=None, question_kind=None)

    async def finish(self, row: HostJob, ending: agent_watch.Ending, result: Optional[str]) -> None:
        store, deps = self.host.store, self._need()
        try:
            totals = await self._read_usage(row)
        except (OSError, ValueError):
            totals = None
        for attempt in (1, 2):
            try:
                await deps.stop_worker(row.worker_session_id or "", row.worker_session_uuid)
                break
            except JobError as exc:
                if attempt == 2:
                    store.host_set(row.job_id, detail="the worker could not be stopped, trying again")
                    log.warning("pack_jobs_agent_finish_stop_failed", job_id=row.job_id, code=exc.code)
                    return
                await deps.sleep(2.0)
        current = store.host_get(row.job_id)
        if current is None or current.state not in (HostState.RUNNING, HostState.PARKED):
            return
        fields: Dict[str, Any] = {"state": HostState.EXITED, "exit_code": ending.code, "detail": ending.detail, "result_text": result,
                                  "question": ending.question, "question_kind": ending.qkind, "parked_at": None, "ended_at": self.host._clock()}
        if totals is not None:
            fields["usage_json"] = json.dumps(totals.model_dump())
        store.host_set(row.job_id, **fields)
        log.info("pack_jobs_agent_finished", job_id=row.job_id, code=ending.code, detail=ending.detail)

    async def abandon(self, job_id: str) -> None:
        row = self.host.store.host_get(job_id)
        if row is not None and row.body == "agent" and row.worker_session_id and self.deps is not None:
            await self._stop_quietly(row.worker_session_id, row.worker_session_uuid)

    async def stop_worker_of(self, job_id: str) -> None:
        row = self.host.store.host_get(job_id)
        if row is None or row.body != "agent":
            return
        task = self._watches.get(job_id)
        if task is not None:
            task.cancel()
            await asyncio.wait({task}, timeout=5.0)
        if row.worker_session_id:
            await self._need().stop_worker(row.worker_session_id, row.worker_session_uuid)


    def fields(self, row: HostJob) -> Dict[str, Any]:
        if row.body != "agent":
            return {}
        out: Dict[str, Any] = {"account_label": row.account_label, "account_how": row.account_how, "worker_session_uuid": row.worker_session_uuid,
                               "usage": UsageTotals.model_validate_json(row.usage_json) if row.usage_json else None}
        if row.state == HostState.PARKED or row.question_kind:
            out.update(question=row.question, question_kind=row.question_kind)
        if row.state == HostState.EXITED:
            out["result_text"] = row.result_text
        return out

    def status(self, row: HostJob) -> StatusAnswer:
        return StatusAnswer(state=row.state, exit_code=row.exit_code, detail=row.detail, **self.fields(row))

    def decorate(self, row: HostJob, answer: CollectAnswer) -> CollectAnswer:
        extra = self.fields(row)
        return answer.model_copy(update=extra) if extra else answer

    async def ensure_watch(self, job_id: str) -> None:
        row = await asyncio.to_thread(self.host.store.host_get, job_id)
        if row is not None and row.body == "agent" and row.state in (HostState.RUNNING, HostState.PARKED) and self.deps is not None:
            self.start_watch(job_id)

    async def sweep_watches(self) -> int:
        if self.deps is None:
            return 0
        rows = await asyncio.to_thread(self.host.store.host_list, [HostState.RUNNING, HostState.PARKED])
        lost = [r for r in rows if r.body == "agent" and r.job_id not in self._watches]
        for row in lost:
            self.start_watch(row.job_id)
        return len(lost)

    async def reply(self, caller: str, body: ReplyBody) -> Dict[str, Any]:
        row, _ = await asyncio.to_thread(self.host._gated_row, caller, body.job_id)
        if row.body != "agent":
            raise JobError("not_an_agent_job", "only an agent job can be answered", 409)
        if row.state != HostState.PARKED:
            raise JobError("not_asking", "the job is not waiting on an answer", 409)
        if row.question_kind not in agent_watch.ASK_KINDS:
            raise JobError("owner_only", "that screen is answered by the owner of this computer", 409)
        if body.question_digest is not None and body.question_digest != digest_of(row.question):
            raise JobError("question_changed", "the worker asked something else since this answer was written", 409)
        deps, sid = self._need(), row.worker_session_id or ""
        if body.job_id in self._replying:
            raise JobError("not_asking", "an answer is already being delivered", 409)
        self._replying.add(body.job_id)
        try:
            if deps.deliver is None:
                raise JobError("agent_not_ready", "this computer cannot type an answer yet", 503)
            before = deps.observe(sid)
            seen = before.cycle if before is not None else -1
            await deps.send_input(sid, _ESCAPE)
            waited = 0.0
            while True:
                obs = deps.observe(sid)
                if obs is not None and obs.cycle > seen:
                    if agent_watch.is_resting(obs):
                        break
                    if agent_watch.classify(obs).kind in ("owner", "dead"):
                        raise JobError("owner_only", "the worker moved on to a screen only this computer's owner may answer; nothing was typed", 409)
                if waited >= _CLEAR_WAIT_S:
                    raise JobError("worker_not_ready", "the worker did not come back to a ready prompt, so nothing was typed", 409)
                await deps.sleep(0.5)
                waited += 0.5
            await deps.deliver(sid, body.text)
            now = self.host._clock()
            self._floors[body.job_id] = now
            self.host.store.host_set(body.job_id, replied_at=now)
            await self._unpark(row)
        finally:
            self._replying.discard(body.job_id)
        return {"ok": True}


    async def _tmux_present(self, row: HostJob) -> bool:
        deps = self._need()
        return bool(row.worker_tmux and deps.present is not None and await deps.present(row.worker_tmux))

    async def recover(self) -> int:
        store, deps, touched = self.host.store, self._need(), 0
        for row in store.host_list([HostState.RUNNING, HostState.PARKED]):
            if row.body != "agent":
                continue
            touched += 1
            if row.worker_session_id and (await deps.listed(row.worker_session_id) or await self._tmux_present(row)):
                self.start_watch(row.job_id)
            else:
                store.host_set(row.job_id, state=HostState.EXITED, exit_code=1, detail=GONE_DETAIL, ended_at=self.host._clock(), parked_at=None)
        for row in store.host_list([HostState.FAILED]):
            if row.body == "agent" and row.detail == RESTART_DETAIL and row.worker_session_id:
                touched += 1
                await self._stop_quietly(row.worker_session_id, row.worker_session_uuid)
                store.host_set(row.job_id, detail=f"{RESTART_DETAIL}; its worker was stopped")
        return touched
