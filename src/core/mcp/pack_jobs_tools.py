
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.api.pack_jobs_routes import JobBody, request_for
from src.core.cross_session_search import strip_ansi
from src.core.mcp import beast_mode, call_budget, pending, wait_tools, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _local_infos, _ok
from src.core.pack.jobs import boot, precheck
from src.core.pack.jobs.agent_account import HOW_WORDS
from src.core.pack.jobs.agent_types import AGENT_NAME_PATTERN, TASK_MAX
from src.core.pack.jobs.engine_agent import AgentRequest
from src.core.pack.jobs.engine_run import load_ctx, request_of
from src.core.pack.jobs.target import SSH_PREFIX
from src.core.pack.jobs.types import TERMINAL, JobError, JobRecord, JobState
from src.core.pack.placement import needs as needs_mod
from src.core.pack.placement.workload import HEAVY_KINDS
from src.core.stream_redactor import redact_whole

logger = structlog.get_logger()

CALL_BUDGET_S = 95.0
JOB_WAIT_MAX_S = 595
JOB_WAIT_DEFAULT_S = 90
RESULT_CHARS = 16384
WORKER_REFUSAL = "you are a job worker: do the work yourself"
RUNNING_NOTE = ("call job_wait again when you need the result in this turn (always, if you are a sub-agent); "
                "if you have other work, do it, and this session gets one message when the job ends.")
TAIL_CHARS = 3000
MAX_PATHS = 50
_MARGIN_S = 2.0

_LOST = "the other computer stopped answering; nothing came back. if it answers again the job is stopped there."
_TODO_BEAST = ("nothing was applied: these files changed here while the job ran. merge the job's version into each yourself "
               "(git diff <base> <ref> -- <file> shows what the job changed). the ref is kept 24 hours.")
_TODO_PLAIN = ("nothing was applied: these files changed here while the job ran. tell the owner which files clashed and the ref; "
               "do not overwrite them. the ref is kept 24 hours.")


def _now() -> float:
    return time.monotonic()


def _engine() -> Any:
    try:
        return boot.engine()
    except JobError as exc:
        raise ToolError(f"{exc.code}: {exc.detail}") from exc


async def _caller_row(manager: Any, caller: AgentCaller) -> Any:
    if caller.from_token or caller.proxied_agent_id:
        raise ToolError("delegate runs only from a session on this computer")
    for info in await _local_infos(manager):
        if info.tmux_session == caller.tmux_name:
            if not info.session_uuid:
                raise ToolError("your session has no database record yet")
            return info
    raise ToolError("your session is not in the live listing")


def _folder(info: Any, folder: Optional[str]) -> str:
    base = info.session.working_dir
    if folder is not None and (not isinstance(folder, str) or not folder.strip()):
        raise ToolError("folder must be text")
    literal = base if not folder else (folder if folder.startswith("/") else os.path.join(base, folder))
    root = os.path.realpath(base)
    real = os.path.realpath(literal)
    if real != root and not real.startswith(root.rstrip("/") + "/"):
        raise ToolError("folder must be the session's working folder or a folder under it")
    return literal


def _cut(paths: Any) -> Dict[str, Any]:
    items = list(paths or [])
    return {"items": items[:MAX_PATHS], **({"more": len(items) - MAX_PATHS} if len(items) > MAX_PATHS else {})}


def _text(value: Optional[str], limit: int) -> str:
    return redact_whole(strip_ansi(value or "").replace("\r", ""))[-limit:]


def _landed(rec: JobRecord) -> Dict[str, Any]:
    try:
        return json.loads(rec.land_json) if rec.land_json else {}
    except ValueError:
        return {}


def _question_fields(rec: JobRecord) -> Dict[str, Any]:
    owner_only = rec.question_kind in ("permission", "startup")
    return {"status": "question", "question": _text(rec.question, RESULT_CHARS), "question_kind": rec.question_kind,
            "next": "owner" if owner_only else "job_reply",
            "note": ("the owner of that computer answers this screen; nothing you send reaches it." if owner_only
                     else "answer it with job_reply (the owner approves the reply); the worker is held about 10 minutes, then stopped and its files come back.")}


def _agent_fields(rec: JobRecord) -> Dict[str, Any]:
    if rec.body != "agent":
        return {}
    out: Dict[str, Any] = {"result_text": _text(rec.result_text, RESULT_CHARS)}
    if rec.question:
        out["question"] = _text(rec.question, RESULT_CHARS)
    try:
        usage = json.loads(rec.usage_json) if rec.usage_json else None
    except ValueError:
        usage = None
    if usage:
        out["usage"] = usage
    if rec.account_label:
        out["account"] = {"label": rec.account_label, "how": rec.account_how, "words": HOW_WORDS.get(rec.account_how or "", "")}
    return out


def agent_result(rec: JobRecord) -> Dict[str, Any]:
    base: Dict[str, Any] = {"status": rec.state.value, "job_id": rec.id, "computer": rec.peer_label}
    state = rec.state
    if state == JobState.HERE:
        return {"decision": "here", "reason": _text(rec.error_detail or rec.reason, 300)}
    if state == JobState.REFUSED:
        return {"decision": "refused", "code": rec.error_code, "reason": _text(rec.error_detail or rec.reason, 300)}
    if state == JobState.WAITING_APPROVAL:
        return {**base, "next": "approval_wait"}
    if state == JobState.QUESTION:
        return {**base, **_question_fields(rec)}
    if state not in TERMINAL:
        started = rec.started_at or rec.created_at
        return {**base, "status": "running", "seconds": max(0, int(time.time() - started)), "next": "job_wait", "note": RUNNING_NOTE}
    if state == JobState.LOST:
        return {**base, "detail": _LOST}
    if state == JobState.STOPPED:
        return base
    if state == JobState.FAILED:
        return {**base, "reason": rec.error_code, "detail": _text(rec.error_detail, 300)}
    land = _landed(rec)
    seconds = max(0, int((rec.ended_at or time.time()) - (rec.started_at or rec.created_at)))
    out: Dict[str, Any] = {**base, "exit_code": rec.exit_code, "seconds": seconds, "output_tail": _text(rec.output_tail, TAIL_CHARS)}
    out.update(_agent_fields(rec))
    if rec.exit_code == 124:
        out["detail"] = "time cap"
    if land.get("clashes"):
        clashes = _cut(land["clashes"])
        out.update(clashes=clashes["items"], ref=land.get("ref"), base=rec.snapshot_commit,
                   todo=_TODO_BEAST if beast_mode.beast_enabled() else _TODO_PLAIN)
        if "more" in clashes:
            out["clashes_more"] = clashes["more"]
        return out
    for key in ("applied", "deleted"):
        cut = _cut(land.get(key))
        out[key] = cut["items"]
        if "more" in cut:
            out[f"{key}_more"] = cut["more"]
    return out


def _job_id(args: dict) -> str:
    value = args.get("job_id")
    if not isinstance(value, str) or not value:
        raise ToolError("job_id is required")
    return value


async def _own_job(manager: Any, caller: AgentCaller, args: dict) -> tuple:
    row = await _caller_row(manager, caller)
    eng = _engine()
    rec = eng.get(_job_id(args))
    if rec is None:
        raise ToolError("unknown_job: no such job")
    if rec.caller_session != row.session_uuid:
        raise ToolError("not a job you started")
    return eng, rec


def _wishes(args: dict) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for key in ("needs", "prefer"):
        try:
            out[key] = [n.text for n in needs_mod.parse_all(args.get(key))]
        except ValueError as exc:
            raise ToolError(f"{key}: {exc}") from exc
    return out


def _body(args: dict, info: Any) -> JobBody:
    unknown = set(args) - {"command", "kind", "folder", "outputs", "time_cap_minutes", "needs", "prefer"}
    if unknown:
        raise ToolError(f"unknown argument: {sorted(unknown)[0]}")
    fields: Dict[str, Any] = {"command": args.get("command"), "folder": _folder(info, args.get("folder"))}
    for key in ("kind", "outputs", "time_cap_minutes"):
        if args.get(key) is not None:
            fields[key] = args[key]
    try:
        return JobBody(**fields)
    except ValueError as exc:
        raise ToolError(f"bad arguments: {str(exc).splitlines()[0][:200]}") from exc


def _agent_request(args: dict, info: Any) -> AgentRequest:
    unknown = set(args) - {"task", "agent_type", "kind", "folder", "outputs", "time_cap_minutes", "needs", "prefer"}
    if unknown:
        raise ToolError(f"unknown argument: {sorted(unknown)[0]}")
    task, agent_type = args.get("task"), args.get("agent_type")
    if not isinstance(task, str) or not task.strip() or len(task) > TASK_MAX or "\0" in task:
        raise ToolError(f"task must be text of 1 to {TASK_MAX} characters")
    if agent_type is not None and (not isinstance(agent_type, str) or not re.fullmatch(AGENT_NAME_PATTERN, agent_type)):
        raise ToolError("agent_type must be an agent's file name: lowercase letters, digits and dashes")
    kind, minutes, outputs = args.get("kind") or "suite", args.get("time_cap_minutes", 60), args.get("outputs") or []
    if kind not in HEAVY_KINDS:
        raise ToolError(f"kind must be one of {', '.join(HEAVY_KINDS)}")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 360:
        raise ToolError("time_cap_minutes must be 1 to 360")
    if not isinstance(outputs, list) or len(outputs) > 20 or not all(isinstance(o, str) and 0 < len(o) <= 256 for o in outputs):
        raise ToolError("outputs: at most 20 paths of at most 256 characters")
    folder = _folder(info, args.get("folder"))
    return AgentRequest(command="", folder=folder, kind=kind, caller_session=info.session_uuid, outputs=list(outputs), time_cap_s=minutes * 60,
                        task=task, agent_type=agent_type, **_wishes(args))


def worker_refusal(info: Any) -> Optional[str]:
    try:
        host = boot.host()
    except JobError:
        return None
    live = host.store.agent_job_for_session(info.session.id, info.session_uuid)
    return WORKER_REFUSAL if live is not None else None


def definition_shown(launch: dict) -> Optional[Dict[str, str]]:
    raw, name = launch.get("definition_json"), launch.get("definition_file")
    if not raw or not name:
        return None
    body = json.loads(raw)
    lists = [f"{label}: {', '.join(str(t) for t in body[key])}" for key, label in (("tools", "tools"), ("disallowedTools", "disallowed tools")) if body.get(key)]
    return {"file": str(name), "prompt": "\n\n".join([str(body.get("prompt") or ""), *lists]) if lists else str(body.get("prompt") or "")}


def _card(args: dict, request: Any, rec: JobRecord) -> Dict[str, Any]:
    installs = load_ctx(rec).get("install") or []
    shown: Dict[str, Any] = {"computer": rec.peer_label, "folder": request.folder, "kind": request.kind, "job_id": rec.id,
                             **({"installs": installs} if installs else {}),
                             **({"ssh": True} if (rec.peer_install_id or "").startswith(SSH_PREFIX) else {}),
                             **({"outputs": request.outputs} if request.outputs else {}),
                             **({"time_cap_minutes": args["time_cap_minutes"]} if args.get("time_cap_minutes") else {})}
    if isinstance(request, AgentRequest):
        launch = request.launch or {}
        text = launch.get("task") or request.task
        definition = definition_shown(launch)
        return {**shown, **({"definition": definition} if definition else {}), "task": text, "agent_type": request.agent_type or "", "family": launch.get("family") or "",
                "permission_mode": launch.get("permission_mode") or "unknown", "model": launch.get("model") or ""}
    return {"command": request.command, **shown}


async def delegate(manager: Any, caller: AgentCaller, args: dict) -> dict:
    deadline = _now() + min(CALL_BUDGET_S, call_budget.current())
    if (args.get("command") is None) == (args.get("task") is None):
        raise ToolError("give exactly one of command (a shell command) or task (work for an agent)")
    row = await _caller_row(manager, caller)
    refused = worker_refusal(row)
    if refused:
        return _ok({"decision": "here", "reason": refused})
    try:
        request = _agent_request(args, row) if args.get("task") is not None else request_for(_body(args, row), row.session_uuid)
        if args.get("task") is None:
            wishes = _wishes(args)
            request.needs, request.prefer = wishes["needs"], wishes["prefer"]
    except JobError as exc:
        raise ToolError(f"{exc.code}: {exc.detail}") from exc
    eng = _engine()
    try:
        rec = await eng.propose(request)
    except JobError as exc:
        raise ToolError(f"{exc.code}: {exc.detail}") from exc
    if rec.state in (JobState.HERE, JobState.REFUSED):
        if rec.state == JobState.HERE:
            precheck.MEMORY.note_here(caller.tmux_name)
        return _ok(agent_result(rec))
    if rec.state == JobState.WAITING_APPROVAL:
        stored = request_of(load_ctx(rec))
        shown = _card(args, stored, rec)

        async def start(_approved: bool) -> dict:
            return _ok(agent_result(await eng.proceed(rec.id)))

        what = f"{stored.agent_type or 'an agent'}: {stored.task[:80]}" if isinstance(stored, AgentRequest) else stored.command[:80]
        summary = f'run on "{rec.peer_label}": {what}'
        parked = await write_tools.park(manager, caller, "", "", "delegate", summary, shown, start, dedupe_key=rec.id,
                                        max_wait=max(0.0, min(pending.MAX_WAIT_SECONDS, deadline - _now() - _MARGIN_S)))
        now_rec = eng.get(rec.id) or rec
        if now_rec.state == JobState.WAITING_APPROVAL:
            return _ok({**wait_tools._payload(parked), "job_id": rec.id, "computer": rec.peer_label, "next": "approval_wait"})
        rec = now_rec
    return _ok(agent_result(await _hold(eng, rec.id, max(0.0, deadline - _now() - _MARGIN_S))))


async def _hold(eng: Any, job_id: str, seconds: float) -> JobRecord:
    eng.waiter_enter(job_id)
    try:
        return await eng.wait(job_id, seconds)
    finally:
        eng.waiter_leave(job_id)


async def job_wait(manager: Any, caller: AgentCaller, args: dict) -> dict:
    eng, rec = await _own_job(manager, caller, args)
    asked = args.get("timeout", JOB_WAIT_DEFAULT_S)
    if isinstance(asked, bool) or not isinstance(asked, (int, float)) or not 1 <= asked <= JOB_WAIT_MAX_S:
        raise ToolError(f"timeout must be 1 to {JOB_WAIT_MAX_S} seconds")
    seconds = max(0.0, min(float(asked), JOB_WAIT_MAX_S, call_budget.current() - 5))
    return _ok(agent_result(await _hold(eng, rec.id, seconds)))


async def job_stop(manager: Any, caller: AgentCaller, args: dict) -> dict:
    eng, rec = await _own_job(manager, caller, args)
    after = await eng.stop(rec.id)
    result = agent_result(after)
    if after.state not in TERMINAL:
        result["note"] = "stop refused: the result is being written into this folder; call job_wait"
    return _ok(result)


def _deny(item: Any) -> None:
    try:
        _engine().cancel(str((item.args or {}).get("job_id", "")))
    except ToolError:
        logger.info("pack_job_deny_no_engine")


pending.on_deny("delegate", _deny)

Handler = Callable[[Any, AgentCaller, dict], Awaitable[dict]]

READ_TOOLS: Dict[str, tuple] = {
    "job_wait": (
        "Wait up to 595 s (default 90) for a job you started with delegate. Answers its result, a worker's question, or status "
        "running: call again with the same job_id when you need the result in this turn (always, if you are a sub-agent).",
        {"job_id": {"type": "string"}, "timeout": {"type": "number", "minimum": 1, "maximum": JOB_WAIT_MAX_S}},
        ["job_id"], job_wait,
    ),
}
WRITE_TOOLS: Dict[str, tuple] = {
    "delegate": (
        "Call BEFORE ANY command that runs code (tests, builds, servers), or to hand a task to an agent of your own kind. Give "
        "exactly one of command or task. Answers here at once when this computer has room: do it yourself. Else the owner "
        "approves (unless Beast Mode is on) and changed files come back. A worker has push blocked by default, not sandboxed. "
        "Same arguments re-attach. Still running: job_wait.",
        {"command": {"type": "string", "maxLength": 8000},
         "task": {"type": "string", "maxLength": TASK_MAX, "description": "what an agent should do in a copy of this folder; shown whole to the owner"},
         "agent_type": {"type": "string", "description": "with task: an agent definition's file name (project, then your profile, then ~/.claude/agents)"},
         "kind": {"type": "string", "enum": list(HEAVY_KINDS)},
         "folder": {"type": "string", "description": "default: this session's folder; must be inside it"},
         "outputs": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
         "needs": {"type": "array", "items": {"type": "string"}, "maxItems": 8,
                   "description": "hard requirements, e.g. xcode, gpu:nvidia, ffmpeg, mem_gb>=32, label:<name>; refused when no computer has them"},
         "prefer": {"type": "array", "items": {"type": "string"}, "maxItems": 8,
                    "description": "soft wishes, same words; they only order computers that already qualify"},
         "time_cap_minutes": {"type": "integer", "minimum": 1, "maximum": 360}},
        [], delegate,
    ),
    "job_stop": (
        "Stop a job you started with delegate. Nothing comes back; the job's folder on the other computer is freed.",
        {"job_id": {"type": "string"}}, ["job_id"], job_stop,
    ),
}
UNGATED_WRITES: frozenset = frozenset()
