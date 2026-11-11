
from __future__ import annotations

import asyncio
from typing import Any, Dict

from src.core.argent import row_state, rollout
from src.core.hosts.identity import is_remote_info

EMPTY: Dict[str, Any] = {"total": 0, "tethered": 0, "pending": 0, "will_restart": 0, "adopted": 0, "subagents": 0, "background": 0, "excluded": {}, "reasons": {}}


async def preview(manager: Any, tenant: str, direction: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {**EMPTY, "excluded": {}, "reasons": {}, "direction": direction}
    for info in await manager.list_session_infos():
        name = info.tmux_session
        if info.agent_family not in rollout.FAMILIES or not name or info.session is None or is_remote_info(info):
            continue
        tether = await asyncio.to_thread(row_state.lookup, tenant, name) if tenant else {"state": "", "reason": ""}
        out["total"] += 1
        if tether["state"] == "tethered":
            out["tethered"] += 1
        elif tether["state"] == row_state.PENDING:
            out["pending"] += 1
        elif tether["state"] == row_state.NOT_TETHERED and tether["reason"]:
            out["reasons"][tether["reason"]] = out["reasons"].get(tether["reason"], 0) + 1
        verdict, reason = rollout.need(direction, tether)
        if verdict == "exclude":
            out["excluded"][reason] = out["excluded"].get(reason, 0) + 1
        elif verdict == "restart":
            out["will_restart"] += 1
            out["adopted"] += 1 if str(info.session.id).startswith("adopted:") else 0
            out["subagents"] += int(info.subagents_running or 0)
            out["background"] += int(info.background_open or 0)
    return out
