
from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

import structlog
from pydantic import ValidationError

from src.core.pack.jobs import agent_facts, member_link
from src.core.pack.jobs.agent_types import CAP_ACCOUNT_IDENTITY, CAP_AGENT, CAP_AGENT_AGY, CAP_REPLY_DIGEST, TASK_MAX, AgentSpec, ReplyBody, digest_of
from src.core.pack.jobs.types import HostState, JobError, JobRecord, JobRequest, JobState, StatusAnswer
from src.core.pack.machines import capabilities

log = structlog.get_logger(__name__)

POLL_FAST_S, POLL_SLOW_S, POLL_FAST_FOR_S = 1.0, 2.0, 10.0
REPLY_TIMEOUT_S = 20.0
NOTIFY_STATES = (JobState.DONE, JobState.FAILED, JobState.LOST)
REPLY_KINDS = ("question", "plan_approval", "input")
FactsFn = Callable[[Optional[str]], Awaitable[agent_facts.CallerFacts]]
NotifierFn = Callable[[Any, JobRecord, str], Awaitable[bool]]


@dataclass
class AgentRequest(JobRequest):

    kind: str = "light"
    task: str = field(default="", kw_only=True)
    agent_type: Optional[str] = field(default=None, kw_only=True)
    launch: Optional[Dict[str, Any]] = field(default=None, kw_only=True)

    def validate(self) -> None:
        JobRequest.validate(dataclasses.replace(self, command="agent"))
        if not 1 <= len(self.task) <= TASK_MAX or "\0" in self.task or not self.task.strip():
            raise JobError("bad_request", f"the task must be 1 to {TASK_MAX} characters", 422)


def idem_extra(req: JobRequest) -> List[Any]:
    return ["agent", req.task, req.agent_type] if isinstance(req, AgentRequest) else []


def agent_columns(req: JobRequest) -> Dict[str, Any]:
    if not isinstance(req, AgentRequest):
        return {}
    launch = req.launch or {}
    return {"body": "agent", "task_head": req.task[:160], "agent_type": req.agent_type, "family": launch.get("family"),
            "permission_mode": launch.get("permission_mode")}


def admit_fields(req: JobRequest) -> Dict[str, Any]:
    launch = req.launch if isinstance(req, AgentRequest) and req.launch else {}
    return {"agent_family": launch["family"], "account_key": launch.get("account_key")} if launch else {}


def agent_spec(req: JobRequest, send_identity: bool = False) -> Optional[AgentSpec]:
    if not isinstance(req, AgentRequest) or req.launch is None:
        return None
    launch = req.launch
    return AgentSpec(task=launch["task"], family=launch["family"], permission_mode=launch["permission_mode"],
                     agent_type=req.agent_type if launch["family"] == "claude" else None, definition_json=launch.get("definition_json"),
                     model=launch.get("model"), account_key=launch.get("account_key"),
                     account_identity=launch.get("account_identity", "") if send_identity else None)


def status_fields(st: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in ("account_label", "account_how", "result_text", "worker_session_uuid"):
        if getattr(st, name, None) is not None:
            out[name] = getattr(st, name)
    usage = getattr(st, "usage", None)
    if usage is not None:
        out["usage_json"] = json.dumps(usage.model_dump())
    return out


def collect_fields(answer: Any) -> Dict[str, Any]:
    out = status_fields(answer)
    if getattr(answer, "question", None) is not None:
        out.update(question=answer.question, question_kind=answer.question_kind)
        out.setdefault("result_text", answer.question)
    return out


class AgentMixin:

    def _agent_init(self, facts_for: Optional[FactsFn], notifier: Optional[NotifierFn]) -> None:
        self._facts_for, self._notifier = facts_for, notifier
        self._waiters: Dict[str, int] = {}
        self._answered: Dict[str, float] = {}
        self._notify_tasks: Set["asyncio.Task[None]"] = set()


    def waiter_enter(self, job_id: str) -> None:
        self._waiters[job_id] = self._waiters.get(job_id, 0) + 1

    def waiter_leave(self, job_id: str) -> None:
        left = self._waiters.get(job_id, 0) - 1
        if left > 0:
            self._waiters[job_id] = left
        else:
            self._waiters.pop(job_id, None)

    def _held(self, job_id: str) -> bool:
        return self._waiters.get(job_id, 0) > 0

    def _notify_soon(self, job_id: str, token: str) -> None:
        if self._notifier is None or self._held(job_id):
            return
        task = self._spawn(self._notify(job_id, token))
        self._notify_tasks.add(task)
        task.add_done_callback(self._notify_tasks.discard)

    async def _notify(self, job_id: str, token: str) -> None:
        rec = self.store.get_job(job_id)
        if rec is None or self._notifier is None:
            return
        try:
            await self._notifier(self.store, rec, token)
        except Exception as exc:  # noqa: BLE001
            log.warning("pack_job_notice_failed", job_id=job_id, error=type(exc).__name__)


    async def _agent_prepare(self, req: AgentRequest) -> None:
        if self._facts_for is None:
            raise JobError("agent_jobs_unavailable", "this computer cannot start agent jobs (no session facts reader)", 503)
        facts = await self._facts_for(req.caller_session)
        task, model, definition, def_file = req.task, facts.model, None, None
        if req.agent_type:
            found = await asyncio.to_thread(agent_facts.read_definition, req.folder, req.agent_type, profile_dir=facts.profile_dir)
            if facts.family == "claude":
                definition, model, def_file = found.definition_json, found.model or model, Path(found.path).name
            else:
                task = f"## Your role\n\n{found.body}\n\n## Your task\n\n{task}"
        if len(task) > TASK_MAX:
            raise JobError("bad_request", f"the task and the agent's role together are longer than {TASK_MAX} characters", 422)
        req.launch = {"family": facts.family, "permission_mode": facts.permission_mode, "model": model, "account_key": facts.account_key,
                      "account_identity": facts.account_identity, "definition_json": definition, "definition_file": def_file, "task": task}

    @staticmethod
    def _agent_view(view: Any, family: Optional[str] = None) -> Any:
        cap = CAP_AGENT_AGY if family == "agy" else CAP_AGENT
        kept = []
        for p in view.peers:
            if not capabilities.has(view.caps.get(p.install_id), cap):
                continue
            if family == "agy":
                tools = ((p.snapshot or {}).get("can") or {}).get("tools")
                if isinstance(tools, dict) and tools.get("agy") is False:
                    continue
            kept.append(p)
        return dataclasses.replace(view, peers=kept)


    async def _poll_agent(self, rec: JobRecord, on_answer: Optional[Callable[[], None]] = None) -> bool:
        began, job_id = self._clock(), rec.id
        while True:
            sampled = self._mono()
            st: StatusAnswer = await self._peer(job_id, rec.peer_install_id or "", lambda t: t.status_full(job_id))
            if on_answer is not None:
                on_answer()
            rec = self.store.get_job(job_id) or rec
            extra = {k: v for k, v in status_fields(st).items() if getattr(rec, k) != v}
            if st.state == HostState.EXITED:
                self.store.set_state(job_id, JobState.COLLECTING, note="the worker finished", exit_code=st.exit_code, output_tail=st.output_tail, **extra)
                return True
            if st.state in (HostState.FAILED, HostState.MISSING, HostState.STOPPED):
                end = JobState.STOPPED if st.state == HostState.STOPPED else JobState.FAILED
                self._end(job_id, end, code=f"host_{st.state.value}", detail=st.detail or f"the job is {st.state.value} on the other computer",
                          exit_code=st.exit_code, output_tail=st.output_tail, **extra)
                return False
            if st.state == HostState.PARKED and self._answered.get(job_id, 0.0) < sampled:
                if rec.state != JobState.QUESTION or rec.question != st.question:
                    rec = self.store.set_state(job_id, JobState.QUESTION, note="the worker asks", question=st.question,
                                               question_kind=st.question_kind, started_at=rec.started_at or self._clock(), **extra)
                    self._notify_soon(job_id, "question")
            elif st.state in (HostState.RUNNING, HostState.PARKED) and (rec.state != JobState.RUNNING or extra):
                if st.state == HostState.RUNNING:
                    clear = {"question": None, "question_kind": None, "notified_state": None} if rec.state == JobState.QUESTION else {}
                    rec = self.store.set_state(job_id, JobState.RUNNING, note="running", started_at=rec.started_at or self._clock(), **clear, **extra)
                elif extra:
                    rec = self.store.set_state(job_id, rec.state, note="usage", **extra)
            await self._sleep(POLL_FAST_S if self._clock() - began < POLL_FAST_FOR_S else POLL_SLOW_S)


    async def _peer_reads_digest(self, rec: JobRecord) -> bool:
        return await self._peer_has(rec, CAP_REPLY_DIGEST)

    async def _peer_has(self, rec: JobRecord, cap: str) -> bool:
        try:
            root = json.loads(rec.request_json or "{}")["snap"]["project_root"]
            view = await asyncio.to_thread(self._view_for, root, rec.project_uid)
        except (JobError, KeyError, ValueError):
            return False
        caps = view.caps.get(rec.peer_install_id or "") or (member_link.caps_for(rec.peer_install_id or "") if member_link.on() else [])
        return capabilities.has(caps, cap)

    async def reply(self, job_id: str, text: str, caller_session: Optional[str], question_digest: Optional[str] = None) -> JobRecord:
        rec = self.store.get_job(job_id)
        if rec is None:
            raise JobError("unknown_job", "no such job", 404)
        if rec.caller_session and rec.caller_session != caller_session:
            raise JobError("not_your_job", "only the session that started the job can answer it", 403)
        if rec.body != "agent":
            raise JobError("not_an_agent_job", "only an agent job can be answered", 409)
        if rec.state != JobState.QUESTION:
            raise JobError("not_asking", "the job is not waiting on an answer", 409)
        if rec.question_kind not in REPLY_KINDS:
            raise JobError("owner_only", "that screen is answered by the owner of the other computer", 409)
        if question_digest is not None and question_digest != digest_of(rec.question):
            raise JobError("question_changed", "the worker asked something else since you wrote this answer; read it and answer again", 409)
        try:
            digest = question_digest if await self._peer_reads_digest(rec) else None
            body = ReplyBody(job_id=job_id, text=text, question_digest=digest)
        except ValidationError as exc:
            raise JobError("bad_request", "the reply must be 1 to 8000 characters with no NUL", 422) from exc
        self._last.setdefault(job_id, self._mono())
        try:
            await asyncio.wait_for(self._peer(job_id, rec.peer_install_id or "", lambda t: t.reply(body)), REPLY_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            raise JobError("unreachable", "the other computer did not answer the reply", 502) from exc
        self._answered[job_id] = self._mono()
        try:
            return self.store.set_state(job_id, JobState.RUNNING, note="answered", question=None, question_kind=None, notified_state=None)
        except JobError as exc:
            if exc.code != "job_ended":
                raise
            return self.store.get_job(job_id) or rec
