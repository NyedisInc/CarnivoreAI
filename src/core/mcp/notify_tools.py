
from __future__ import annotations

from typing import Any, Optional

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.notifications import agent_message

NAME = "notify"


def hidden_reason(caller: Optional[AgentCaller], name: str) -> str:
    if name != NAME:
        return ""
    if caller is not None and caller.external:
        return "notify is for a running pane, not an external token"
    if not agent_message.enabled():
        return "notify is off (the owner turned off agent notify)"
    return ""


async def notify(manager: Any, caller: AgentCaller, args: dict) -> dict:
    app = getattr(manager, "app", None)
    if app is None:
        raise ToolError("notify is unavailable on this transport")
    reason = hidden_reason(caller, NAME)
    if reason:
        raise ToolError(reason)
    try:
        return _ok(await agent_message.send(app.state.session_manager, caller.current_session_id, args.get("text")))
    except agent_message.AgentNotifyError as exc:
        retry = f" (retry in {exc.retry_after} s)" if exc.retry_after is not None else ""
        raise ToolError(exc.message + retry) from exc


WRITE_TOOLS: dict = {
    NAME: (
        "Send the owner a short notification about THIS session (it is routed by the owner's notification settings). "
        "At most 280 characters, secrets are starred, and calls are rate limited (3 a minute, 5 per 10 minutes).",
        {"text": {"type": "string", "maxLength": 280}}, ["text"], notify),
}
