
from __future__ import annotations

import json
from typing import Any

from src.core.hosts.ddl import LOCAL_HOST_KEY


_TARGET_SCHEMA = {
    "type": "string",
    "description": "Session id, adopted:<name> or tmux name. Required; never defaults to your own session.",
}


class ToolError(Exception):
    pass


def _ok(payload: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _fail(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


async def _local_infos(manager: Any) -> list:
    infos = await manager.list_session_infos()
    return [i for i in infos if i.host_key == LOCAL_HOST_KEY]


async def _all_infos(manager: Any) -> list:
    return await _local_infos(manager) + await manager.list_peer_infos()


def _summary(info: Any) -> dict:
    row = {
        "id": info.session.id,
        "tmux_session": info.tmux_session,
        "label": info.label,
        "agent_type": info.agent_type or info.session.agent_type,
        "project": info.project_name,
        "working_dir": info.session.working_dir,
        "activity_status": info.activity_status,
        "unread": info.unread,
    }
    if info.host_key != LOCAL_HOST_KEY:
        row.update(host=info.host_label, host_state=info.host_state)
    if info.task_lead is not None:
        row.update(task_lead=info.task_lead, do_not_disturb=info.do_not_disturb)
    return row


def _resolve(infos: list, args: dict) -> Any:
    target = args.get("target")
    if not isinstance(target, str) or not target.strip():
        raise ToolError("target is required: a session id, adopted:<name> or tmux name")
    target = target.strip()
    for info in infos:
        if info.session.id == target:
            return info
    for info in infos:
        if info.tmux_session == target and info.host_key == LOCAL_HOST_KEY:
            return info
    raise ToolError(f"no live session matches target {target!r}")
