
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from src.core.cross_session_search import strip_ansi
from src.core.mcp import federated, session_target, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _ok
from src.core.session_output import cursor as pipe_cursor
from src.core.session_output import waits
from src.core.stream_redactor import redact_whole

_DIALOG_KEYS = ("kind", "title", "question", "prompt", "summary")


def _decode(raw: bytes) -> str:
    return strip_ansi(raw.decode("utf-8", errors="replace")).replace("\r", "")


def _spec(args: dict, *, need_until: bool) -> waits.WaitSpec:
    until = args.get("until", {})
    if not isinstance(until, dict) or set(until) - {"state", "output_contains"}:
        raise ToolError("until must be an object with state (a list) and/or output_contains (a string)")
    states = until.get("state", [])
    if isinstance(states, str):
        states = [states]
    if not isinstance(states, list) or any(s not in waits.STATE_SETS for s in states):
        raise ToolError(f"until.state must be a list of: {', '.join(waits.STATE_SETS)}")
    text = until.get("output_contains")
    if text is not None and (not isinstance(text, str) or not 1 <= len(text) <= waits.MAX_TEXT_CHARS or "\n" in text):
        raise ToolError(f"until.output_contains must be one line of 1 to {waits.MAX_TEXT_CHARS} characters (plain text, no regex)")
    if need_until and not states and text is None:
        raise ToolError("until needs a state or output_contains")
    timeout = args.get("timeout", waits.MAX_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= waits.MAX_TIMEOUT_SECONDS:
        raise ToolError(f"timeout must be 1 to {int(waits.MAX_TIMEOUT_SECONDS)} seconds")
    quiet = args.get("min_quiet", 0)
    if isinstance(quiet, bool) or not isinstance(quiet, (int, float)) or not 0 <= quiet <= waits.MAX_MIN_QUIET_SECONDS:
        raise ToolError(f"min_quiet must be 0 to {int(waits.MAX_MIN_QUIET_SECONDS)} seconds")
    return waits.WaitSpec(tuple(dict.fromkeys(states)), text, float(timeout), float(quiet))


def _since(args: dict) -> Optional[pipe_cursor.Cursor]:
    if args.get("since") is None:
        return None
    try:
        return pipe_cursor.parse(args["since"])
    except pipe_cursor.CursorError as exc:
        raise ToolError(str(exc)) from exc


async def _wait(manager: Any, caller: AgentCaller, info: Any, spec: waits.WaitSpec,
                since: Optional[pipe_cursor.Cursor], initial_status: Optional[str]) -> dict:
    sid = info.session.id
    remote = federated.is_remote(info)
    if remote and (spec.text is not None or since is not None):
        raise ToolError("a paired computer's session supports state waits only (no output_contains, no since)")
    basis = None if remote else manager.pipe_basis(sid)
    if spec.text is not None and basis is None:
        raise ToolError("that session has no output file to wait on; wait on a state instead")
    try:
        outcome = await waits.run_wait(
            registry=waits.REGISTRY, session_id=sid, caller=waits.caller_key(caller), spec=spec,
            initial_status=initial_status, pipe=waits.PipeSource(basis) if basis else None, since=since,
            is_gone=(lambda: False) if remote else (lambda: not manager.has_session(sid)),
            decode=_decode, clean=redact_whole)
    except waits.WaitLimitError as exc:
        raise ToolError(f"{exc}; retry in {exc.retry_after} s") from exc
    answer = {"status": outcome.status, "matched": outcome.matched, "state": outcome.state,
              "cursor": outcome.cursor, "elapsed_s": outcome.elapsed_s}
    if outcome.tail:
        answer["tail"] = outcome.tail
    if outcome.state in waits.STATE_SETS["blocked"]:
        answer["dialog"] = await _dialog_summary(manager, info)
    return answer


async def _dialog_summary(manager: Any, info: Any) -> Optional[dict]:
    from src.core.mcp import dialog_tools

    try:
        dialog = await dialog_tools._shown_dialog(manager, info)
    except ToolError:
        return None
    if not isinstance(dialog, dict):
        return None
    shown = {k: redact_whole(str(dialog[k]))[:500] for k in _DIALOG_KEYS if dialog.get(k)}
    options = dialog.get("options")
    if isinstance(options, list):
        shown["options"] = [redact_whole(str(o.get("label", o) if isinstance(o, dict) else o))[:120] for o in options[:10]]
    return shown


async def session_wait(manager: Any, caller: AgentCaller, args: dict) -> dict:
    spec = _spec(args, need_until=True)
    since = _since(args)
    info = await session_target.live_info(manager, args, "session_wait")
    return _ok(await _wait(manager, caller, info, spec, since, info.activity_status))


async def session_send_and_wait(manager: Any, caller: AgentCaller, args: dict) -> dict:
    spec = _spec(args, need_until=False)
    states = tuple(dict.fromkeys((*(spec.states or (() if spec.text else ("idle",))), "blocked")))
    spec = waits.WaitSpec(states, spec.text, spec.timeout, spec.min_quiet)
    info = await session_target.live_info(manager, args, "session_send_and_wait")
    basis = None if federated.is_remote(info) else manager.pipe_basis(info.session.id)
    before = None
    if basis is not None:
        path, stamp = basis()
        before = await asyncio.to_thread(pipe_cursor.at_end, path, stamp)
    sent = await write_tools.session_send_message(manager, caller, {"target": info.session.id, "text": args.get("text")})
    if sent.get("isError"):
        return sent
    payload = _payload(sent)
    if payload.get("status") == "pending":
        return _ok({**payload, "cursor": before.encode() if before else None,
                    "next": "approval_wait with this id, then session_wait with since set to cursor"})
    answer = await _wait(manager, caller, info, spec, before, None)
    if answer["state"] in waits.STATE_SETS["blocked"] and answer["status"] == waits.MATCHED:
        answer["status"] = "blocked"
    return _ok({**answer, "sent": {k: payload[k] for k in ("id", "status") if k in payload}})


def _payload(result: dict) -> dict:
    try:
        parsed = json.loads(result["content"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


_UNTIL_SCHEMA = {
    "type": "object",
    "description": "Any of: state (list of idle, blocked, waiting, exited) or output_contains (plain text in NEW output).",
    "properties": {"state": {"type": "array", "items": {"type": "string", "enum": list(waits.STATE_SETS)}},
                   "output_contains": {"type": "string", "maxLength": waits.MAX_TEXT_CHARS}},
}
_WAIT_PROPS = {
    "until": _UNTIL_SCHEMA,
    "timeout": {"type": "number", "minimum": 1, "maximum": waits.MAX_TIMEOUT_SECONDS},
    "min_quiet": {"type": "number", "minimum": 0, "maximum": waits.MAX_MIN_QUIET_SECONDS,
                  "description": "seconds a state must hold"},
}

Handler = Callable[[Any, AgentCaller, dict], Awaitable[dict]]

READ_TOOLS: dict[str, tuple[str, dict, list, Handler]] = {
    "session_wait": (
        "Wait up to 50 s until a session reaches a state or prints text. Answers matched, still_waiting (call again with "
        "since=cursor), cursor_reset or session_gone.",
        {"target": _TARGET_SCHEMA, **_WAIT_PROPS,
         "since": {"type": "string", "description": "cursor from an earlier answer"}},
        ["target", "until"], session_wait,
    ),
}
WRITE_TOOLS: dict[str, tuple[str, dict, list, Handler]] = {
    "session_send_and_wait": (
        "session_send_message, then session_wait (default until idle). A dialog ends it as blocked; pending means "
        "approval_wait, then session_wait with since.",
        {"target": _TARGET_SCHEMA, "text": {"type": "string", "maxLength": write_tools.MAX_MESSAGE_CHARS}, **_WAIT_PROPS},
        ["target", "text"], session_send_and_wait,
    ),
}
