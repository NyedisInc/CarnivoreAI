
from __future__ import annotations

import hashlib
from typing import Any, Dict

from src.core.mcp import call_budget, pending, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.pack_jobs_tools import _caller_row, _own_job, agent_result, worker_refusal
from src.core.pack.jobs.agent_types import ReplyBody
from src.core.pack.jobs.engine_agent import digest_of
from src.core.pack.jobs.types import JobError, JobState

_MARGIN_S = 2.0
REPLY_MAX = 8000


async def job_reply(manager: Any, caller: AgentCaller, args: dict) -> dict:
    unknown = set(args) - {"job_id", "text"}
    if unknown:
        raise ToolError(f"unknown argument: {sorted(unknown)[0]}")
    row = await _caller_row(manager, caller)
    if worker_refusal(row):
        raise ToolError("job_reply refused: you are a job worker; do the work yourself")
    eng, rec = await _own_job(manager, caller, args)
    text = args.get("text")
    try:
        ReplyBody(job_id=rec.id, text=text)
    except ValueError as exc:
        raise ToolError(f"text must be 1 to {REPLY_MAX} characters") from exc
    if rec.state != JobState.QUESTION:
        raise ToolError("not_asking: the job is not waiting on an answer")
    if rec.question_kind in ("permission", "startup"):
        raise ToolError("owner_only: that screen is answered by the owner of the other computer")
    shown: Dict[str, Any] = {"job_id": rec.id, "computer": rec.peer_label, "question": rec.question or "", "text": text}
    asked = digest_of(rec.question)

    async def send(_approved: bool) -> dict:
        try:
            return _ok(agent_result(await eng.reply(rec.id, text, row.session_uuid, asked)))
        except JobError as exc:
            raise ToolError(f"{exc.code}: {exc.detail}") from exc

    key = f"{rec.id}:{asked}:{hashlib.sha256(text.encode()).hexdigest()[:8]}"
    summary = f'answer the worker on "{rec.peer_label}": {text[:80]}'
    return await write_tools.park(manager, caller, "", "", "job_reply", summary, shown, send, dedupe_key=key,
                                    max_wait=max(0.0, min(pending.MAX_WAIT_SECONDS, call_budget.current() - _MARGIN_S)))


READ_TOOLS: Dict[str, tuple] = {}
WRITE_TOOLS: Dict[str, tuple] = {
    "job_reply": (
        "Answer the question of a worker on a job you started with delegate (job_wait said status question). The owner approves "
        "the text unless Beast Mode is on. Permission and startup screens are the owner's, not yours. The worker is held about "
        "10 minutes, then stopped.",
        {"job_id": {"type": "string"}, "text": {"type": "string", "maxLength": REPLY_MAX}}, ["job_id", "text"], job_reply,
    ),
}
UNGATED_WRITES: frozenset = frozenset()
