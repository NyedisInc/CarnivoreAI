
from __future__ import annotations

from typing import Any, Optional

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.notifications import agent_message

NAME = "notify"
REVIEW_NAME = "review_send"


def hidden_reason(caller: Optional[AgentCaller], name: str) -> str:
    if name not in (NAME, REVIEW_NAME):
        return ""
    if caller is not None and caller.external:
        return f"{name} is for a running pane, not an external token"
    if not agent_message.enabled():
        return f"{name} is off (the owner turned off agent notify)"
    return ""


async def _send(manager: Any, caller: AgentCaller, name: str, args: dict, review: bool) -> dict:
    app = getattr(manager, "app", None)
    if app is None:
        raise ToolError(f"{name} is unavailable on this transport")
    reason = hidden_reason(caller, name)
    if reason:
        raise ToolError(reason)
    try:
        return _ok(await agent_message.send(app.state.session_manager, caller.current_session_id, args.get("text"),
                                            attachment=args.get("attachment"), app_state=app.state, review=review))
    except agent_message.AgentNotifyError as exc:
        retry = f" (retry in {exc.retry_after} s)" if exc.retry_after is not None else ""
        raise ToolError(exc.message + retry) from exc


async def notify(manager: Any, caller: AgentCaller, args: dict) -> dict:
    return await _send(manager, caller, NAME, args, review=False)


async def review_send(manager: Any, caller: AgentCaller, args: dict) -> dict:
    return await _send(manager, caller, REVIEW_NAME, args, review=True)


_ATTACHMENT: dict = {"type": "object", "additionalProperties": False,
                     "properties": {"path": {"type": "string", "description": "absolute path of a file inside this project"},
                                    "url": {"type": "string", "maxLength": 2000, "description": "https link, shown by its real host"},
                                    "title": {"type": "string", "maxLength": 120}}}

WRITE_TOOLS: dict = {
    NAME: (
        "Send the owner one short notification about THIS session, routed by his notification settings. "
        "Text up to 280 characters, secrets starred, rate limited (3 a minute, 5 per 10 minutes). "
        "Optional `attachment` (iPhone and this computer only): `path` (absolute, inside this project; image 10 MB, "
        "video 50 MB, file 25 MB; credential text refused) or `url` (https, never fetched), plus `title`.",
        {"text": {"type": "string", "maxLength": 280}, "attachment": _ATTACHMENT},
        ["text"], notify),
    REVIEW_NAME: (
        "Send the owner something TO REVIEW (link, file, mockup, report) on his iPhone and this computer; "
        "tapping it opens the item. Use it when he asked to be sent something when done, or you have something ready, "
        "instead of notify or a text. `text` (280 characters) says what; `attachment` is required: one of `path` "
        "(a file in this project) or `url` (https), optional `title`.",
        {"text": {"type": "string", "maxLength": 280}, "attachment": _ATTACHMENT},
        ["text", "attachment"], review_send),
}
