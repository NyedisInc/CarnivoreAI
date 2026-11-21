
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from src.core.attention.transcript_records import is_interrupt, tag_value
from src.core.attention.turn_counts import KIND_AGENT, async_launch, content_blocks
from src.core.timeline import prompts
from src.core.timeline.context import ExtractContext, LineScope, ToolRef
from src.core.timeline.model import Kind, is_ident
from src.core.transcript_contract.stop_reasons import END_STOPS

VIA_STOP_REASON, VIA_INTERRUPT, VIA_NOTIFICATION = "stop_reason", "interrupt", "notification"
END_NORMAL, END_INTERRUPTED = "normal", "interrupted"
END_ERROR, END_USAGE_LIMIT = "error", "usage_limit"

AGENT_TOOLS = frozenset({"Agent", "Task"})
TODO_TOOLS: Mapping[str, str] = {"TodoWrite": "write", "TaskCreate": "create", "TaskUpdate": "update"}
TODO_STATES = ("pending", "in_progress", "completed")

SYNTHETIC_MODEL = "<synthetic>"
USAGE_LIMIT_RE = re.compile(r"\b(?:usage|rate) limit\b", re.I)
AGENT_ID_RE = re.compile(r"agentId:\s*([0-9A-Za-z]{6,40})")

END_MAX_TOKENS = "max_tokens"
STOP_END: Mapping[str, str] = {"end_turn": END_NORMAL, "stop_sequence": END_NORMAL, "max_tokens": END_MAX_TOKENS,
                               "refusal": "refusal"}


def ident(value: Any) -> Optional[str]:
    return value if is_ident(value) else None


def _is_interrupt(record: Mapping[str, Any]) -> bool:
    return is_interrupt({**record, "isSidechain": False})


def _turn_end(scope: LineScope, via: str, end: str, **extra: Any) -> None:
    merged = scope.close_turn()
    scope.emit(Kind.TURN_END, {"via": via, "end": end, "merged": True if merged else None, **extra})


def _content_bytes(content: Any) -> int:
    if isinstance(content, str):
        return len(content.encode("utf-8", "replace"))
    return len(json.dumps(content, ensure_ascii=False).encode("utf-8", "replace"))


def _record_tasks(ctx: ExtractContext, record: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    launch = async_launch(record)
    task_ids: Dict[str, Optional[str]] = {}
    for block in content_blocks(record, "tool_result"):
        call_id = ident(block.get("tool_use_id")) or ""
        ref = ctx.tools.get(call_id)
        task_id = launch.task_id if launch and launch.tool_use_id in (None, call_id) else None
        if ref and ref.name in AGENT_TOOLS and task_id is None:
            found = AGENT_ID_RE.search(prompts.text_of(block.get("content")))
            task_id = found.group(1) if found else None
        if task_id and ref and ref.name in AGENT_TOOLS:
            ctx.tasks[task_id] = KIND_AGENT
        task_ids[call_id] = task_id
    if launch and launch.kind != KIND_AGENT and launch.task_id:
        ctx.tasks[launch.task_id] = launch.kind
    return task_ids


def _tool_results(scope: LineScope) -> None:
    record, ctx = scope.record, scope.ctx
    task_ids = _record_tasks(ctx, record)
    for block in content_blocks(record, "tool_result"):
        call_id = ident(block.get("tool_use_id"))
        ref = ctx.tools.get(call_id or "")
        scope.emit(Kind.TOOL_RESULT, {
            "tool_use_id": call_id, "name": ref.name if ref else None, "ok": block.get("is_error") is not True,
            "bytes": _content_bytes(block.get("content")), "task_id": task_ids.get(call_id or ""),
        }, parent=ref.call_id if ref else None)
    launch = async_launch(record)
    if launch and launch.kind != KIND_AGENT and launch.task_id:
        ref = ctx.tools.get(launch.tool_use_id or "")
        scope.emit(Kind.BG_START, {
            "task_id": launch.task_id, "tool_use_id": launch.tool_use_id, "bg_kind": launch.kind,
        }, parent=ref.call_id if ref else None)


def learn_inherited(ctx: ExtractContext, record: Mapping[str, Any]) -> None:
    if record.get("type") == "assistant":
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        for block in message.get("content") if isinstance(message.get("content"), list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and ident(block.get("id")):
                ctx.tools[ident(block["id"]) or ""] = ToolRef(ident(block.get("name")) or "", None)
    elif record.get("type") == "user":
        _record_tasks(ctx, record)


def notification_events(scope: LineScope, text: str) -> None:
    task_id, tool_use_id = tag_value(text, "task-id"), tag_value(text, "tool-use-id")
    status = tag_value(text, "status")
    bg_kind = scope.ctx.tasks.get(task_id or "")
    ref = scope.ctx.tools.get(tool_use_id or "")
    if bg_kind is None and ref and ref.name in AGENT_TOOLS:
        bg_kind = KIND_AGENT
    ids = {"task_id": ident(task_id), "tool_use_id": ident(tool_use_id)}
    if status and bg_kind == KIND_AGENT:
        scope.emit(Kind.SUBAGENT_END, {
            "agent_id": ids["task_id"], "tool_use_id": ids["tool_use_id"], "status": ident(status),
            "via": VIA_NOTIFICATION,
        })
    elif status:
        scope.emit(Kind.BG_END, {**ids, "bg_kind": bg_kind, "status": ident(status), "via": VIA_NOTIFICATION})
    scope.emit(Kind.NOTICE, {"what": "task_notification", "task_id": ids["task_id"], "status": ident(status)})


def user_record(scope: LineScope) -> None:
    record, ctx = scope.record, scope.ctx
    text = prompts.user_text(record)
    if record.get("isCompactSummary") is True:
        scope.emit(Kind.COMPACTION, {"phase": "summary"}, parent=ctx.compaction_id)
    elif _is_interrupt(record):
        _turn_end(scope, VIA_INTERRUPT, END_INTERRUPTED)
    elif content_blocks(record, "tool_result"):
        _tool_results(scope)
    elif prompts.is_task_notice(record, text):
        if ctx.turn is None or ctx.turn_ended:
            scope.open_turn()
        notification_events(scope, text)
    elif text.lstrip().startswith((prompts.COMMAND_NAME_PREFIX, prompts.LOCAL_OUTPUT_PREFIX)):
        output = text.lstrip().startswith(prompts.LOCAL_OUTPUT_PREFIX)
        scope.emit(Kind.COMMAND, {
            "name": ident(prompts.command_name(text)), "part": "output" if output else "invocation", "via": "user",
        })
    elif record.get("isMeta") is not True or prompts.is_delivered(record):
        _prompt(scope, text)


def _prompt(scope: LineScope, text: str) -> None:
    body, wrapped = prompts.unwrap_pasted(text)
    scope.open_turn()
    scope.emit(Kind.PROMPT, {
        "origin": prompts.prompt_origin(scope.record, body), "plain": prompts.is_plain(scope.record, body),
        "wrapped": True if wrapped else None, "chars": len(body),
        "attachments": prompts.attachment_kinds(scope.record) or None,
    })


def _todo_data(name: str, tool_input: Mapping[str, Any]) -> Dict[str, Any]:
    items = tool_input.get("todos") if isinstance(tool_input.get("todos"), list) else []
    states = [item.get("status") for item in items if isinstance(item, dict)]
    count = len(states) if name == "TodoWrite" else 1
    counts = {state: states.count(state) for state in TODO_STATES if state in states}
    return {"op": TODO_TOOLS[name], "count": count, **counts}


def _tool_use(scope: LineScope, block: Mapping[str, Any], msg: Optional[str]) -> None:
    name, call_id = ident(block.get("name")) or "", ident(block.get("id"))
    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    call = scope.emit(Kind.TOOL_CALL, {"tool_use_id": call_id, "name": name}, msg=msg)
    if call_id:
        scope.ctx.tools[call_id] = ToolRef(name, call.id)
    if name in AGENT_TOOLS:
        scope.emit(Kind.SUBAGENT_START, {"tool_use_id": call_id, "type": ident(tool_input.get("subagent_type")),
                                         "background": tool_input.get("run_in_background") is True or None},
                   parent=call.id, msg=msg)
    if name in TODO_TOOLS:
        scope.emit(Kind.TODO, _todo_data(name, tool_input), parent=call.id, msg=msg)


def _blocks(scope: LineScope, blocks: List[Mapping[str, Any]], msg: Optional[str], model: Optional[str],
            final: bool) -> None:
    last_text = max((i for i, b in enumerate(blocks) if b.get("type") == "text"), default=-1)
    for index, block in enumerate(blocks):
        kind = block.get("type")
        if kind == "text":
            scope.emit(Kind.REPLY, {"model": model, "final": True if final and index == last_text else None,
                                    "chars": len(str(block.get("text") or ""))}, msg=msg)
        elif kind == "thinking":
            scope.emit(Kind.THINKING, {"chars": len(str(block.get("thinking") or ""))}, msg=msg)
        elif kind == "tool_use":
            _tool_use(scope, block, msg)
        else:
            scope.emit(Kind.UNKNOWN, {"record_type": "assistant", "block": ident(kind)}, msg=msg)


def _only_thinking(blocks: List[Mapping[str, Any]]) -> bool:
    return bool(blocks) and all(block.get("type") == "thinking" for block in blocks)


def _has_tool_use(blocks: List[Mapping[str, Any]]) -> bool:
    return any(block.get("type") == "tool_use" for block in blocks)


def _place_in_turn(scope: LineScope, msg: Optional[str], blocks: List[Mapping[str, Any]]) -> None:
    ctx = scope.ctx
    if ctx.turn is not None and not ctx.turn_ended:
        return
    same_message = bool(msg) and msg == ctx.closed_msg
    if ctx.turn is not None and ((same_message and _has_tool_use(blocks)) or ctx.closed_end == END_MAX_TOKENS):
        scope.reopen_turn()
    elif not same_message:
        scope.open_turn()


def assistant_record(scope: LineScope) -> None:
    record = scope.record
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    msg = ident(message.get("id"))
    if message.get("model") == SYNTHETIC_MODEL or record.get("isApiErrorMessage") is True or record.get("apiError"):
        _synthetic(scope, message)
        return
    stop = message.get("stop_reason")
    stop = stop if isinstance(stop, str) else None
    content = message.get("content") if isinstance(message.get("content"), list) else []
    blocks = [b for b in content if isinstance(b, dict)]
    _place_in_turn(scope, msg, blocks)
    closes = stop in END_STOPS and not _only_thinking(blocks) and not _has_tool_use(blocks)
    _blocks(scope, blocks, msg, ident(message.get("model")), final=closes)
    if closes:
        first = not scope.ctx.turn_ended
        _turn_end(scope, VIA_STOP_REASON, STOP_END[stop])
        if first:
            scope.ctx.closed_msg, scope.ctx.closed_end = msg, STOP_END[stop]


def _synthetic(scope: LineScope, message: Mapping[str, Any]) -> None:
    errored = scope.record.get("isApiErrorMessage") is True or bool(scope.record.get("apiError"))
    limited = errored and bool(USAGE_LIMIT_RE.search(prompts.text_of(message.get("content"))))
    what = "usage_limit" if limited else "api_error" if errored else "info"
    scope.emit(Kind.NOTICE, {"what": what, "subtype": None if errored else "resume_placeholder"})
    if errored:
        _turn_end(scope, VIA_STOP_REASON, END_USAGE_LIMIT if limited else END_ERROR)
