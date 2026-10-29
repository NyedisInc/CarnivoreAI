
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

from src.core.mcp import aliases, pending
from src.core.mcp.approvals import call_context, persist
from src.core.mcp.common import _local_infos

logger = structlog.get_logger()


def _view(app: Any) -> Any:
    from src.core.mcp.protocol import BatchView  # noqa: PLC0415

    return BatchView(app.state.session_manager, app)


async def install(app: Any) -> int:
    from src.config import settings  # noqa: PLC0415
    from src.config.errors import StateDirUnavailableError  # noqa: PLC0415

    store = pending.get_store()
    store.set_runtime(lambda item: recheck(app, item), lambda item: replay(app, item))
    try:
        file = persist.open_in(settings.get_state_dir())
    except StateDirUnavailableError as exc:
        logger.error("agent_actions_state_dir_unavailable", error=str(exc))
        return 0
    return store.attach(file) if file is not None else 0


async def pin(manager: Any, target_id: str) -> Tuple[Optional[int], str]:
    if not target_id or target_id.startswith("remote:"):
        return None, ""
    for info in await _local_infos(manager):
        if info.session.id == target_id:
            return info.session.tmux_created_epoch, info.label or info.tmux_session or ""
    return None, ""


async def recheck(app: Any, item: pending.PendingAction) -> str:
    if item.target_epoch is None:
        return ""
    name = item.target_name or item.target_tmux or item.target_session_id
    now = next((i for i in await _local_infos(_view(app)) if i.session.id == item.target_session_id), None)
    if now is None:
        return f"the target session {name} is gone"
    if now.session.tmux_created_epoch != item.target_epoch:
        return f"the id of {name} now points at a different tmux instance than the one you were asked about"
    return ""


def expected_of(item: pending.PendingAction) -> Dict[str, Any]:
    return {"action": aliases.canonical(item.action), "target_id": item.target_session_id, "target_tmux": item.target_tmux,
            "epoch": item.target_epoch, "args": _normal(item.args), "dedupe_key": item.dedupe_key}


def _normal(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def canonicalize_expected(replay: call_context.Replay, canonical: Callable[[dict], dict]) -> None:
    replay.expected["args"] = _normal(canonical(dict(replay.expected.get("args") or {})))


def mismatch(replay: call_context.Replay, *, action: str, target_id: str, target_tmux: str, epoch: Optional[int],
             args: dict, dedupe_key: str) -> str:
    want = replay.expected
    if action != want["action"]:
        return "the call now asks for a different action than the one you approved"
    if (target_id, target_tmux) != (want["target_id"], want["target_tmux"]):
        return "the target now resolves to a different session than the one you approved"
    if epoch != want["epoch"]:
        return "the id now points at a different tmux instance than the one you were asked about"
    if _normal(args) != want["args"] or dedupe_key != want["dedupe_key"]:
        return "what it would do changed since you were asked"
    return ""


def _text(result: Any) -> str:
    blocks = result.get("content") if isinstance(result, dict) else None
    first = blocks[0].get("text") if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict) else ""
    return str(first or "")[:300]


async def replay(app: Any, item: pending.PendingAction) -> dict:
    if not item.tool:
        raise pending.ActionRefused("it was asked before a restart and its call was not kept; ask the agent to send it again")
    from src.core.mcp import tools  # noqa: PLC0415

    marker = call_context.Replay(action_id=item.id, expected=expected_of(item))
    with call_context.replaying(marker):
        result = await tools.call_tool(_view(app), item.caller(), item.tool, dict(item.tool_args))
    if marker.refused:
        raise pending.ActionRefused(marker.refused)
    if not marker.consumed and isinstance(result, dict) and result.get("isError"):
        raise pending.ActionRefused(_text(result) or "the tool refused it")
    logger.info("agent_action_replayed", id=item.id, tool=item.tool, parked=marker.consumed)
    return result
