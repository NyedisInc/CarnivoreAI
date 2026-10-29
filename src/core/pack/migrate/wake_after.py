
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

from src.core.pack.migrate.live_agents import LiveAgent
from src.core.pack.migrate.plan import MigrateError, Request


async def _wake_one(request: Request, agent: LiveAgent) -> Tuple[str, str]:
    try:
        status, answer = await request("POST", f"/sessions/{quote(agent.session_uuid, safe='')}/wake", json={})
    except MigrateError as exc:
        return agent.name, exc.detail
    body = answer if isinstance(answer, dict) else {}
    if status == 200 and body.get("status") == "started":
        return agent.name, ""
    detail = body.get("detail")
    reason = detail.get("detail") if isinstance(detail, dict) else detail
    return agent.name, str(reason or body.get("status") or f"the other computer answered {status}")[:200]


async def wake_all(request: Request, agents: List[LiveAgent]) -> Dict[str, Any]:
    results = await asyncio.gather(*(_wake_one(request, a) for a in agents))
    failed = [{"name": name, "reason": reason} for name, reason in results if reason]
    return {"woken": len(results) - len(failed), "wake_failed": failed}
