
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.automations import models as m
from src.core.automations import targets
from src.core.automations import notify_policy


def validate_target(target: Dict[str, Any]) -> Optional[str]:
    for index, step in enumerate(target.get("steps") or (), start=1):
        check = targets.VALIDATORS.get(step.get("kind") or "")
        problem = check(step) if check else None
        if problem:
            return f"step_{index}_{problem}"
    return None


async def login_hint(app_state: Any, target: Dict[str, Any]) -> Optional[str]:
    last = (target.get("steps") or [{}])[-1]
    hinter = targets.LOGIN_HINTS.get(last.get("kind") or "")
    return await hinter(app_state, last) if hinter else None


def _quiet(automation: Dict[str, Any], step: Dict[str, Any]) -> Dict[str, Any]:
    return {**automation, "target": step, "delivery": {**automation["delivery"], "notify": False}}


def _tell_once(automation: Dict[str, Any], run_row: Dict[str, Any], outcome: m.RunOutcome, store: Any = None) -> None:
    delivery = automation["delivery"]
    if not delivery.get("notify", True) or outcome.status in m.LIVE_STATUSES:
        return
    if outcome.status not in (m.FAILED, m.SUCCEEDED):
        return
    notice = notify_policy.decide(automation, outcome.status == m.FAILED)
    if notice:
        notify_policy.tell(notice, automation, run_row["run_id"], store)


async def run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    done: List[Dict[str, Any]] = []
    cost: Optional[float] = None
    usage: Optional[Dict[str, int]] = None
    outcome = m.RunOutcome(status=m.SUCCEEDED)
    for step in automation["target"]["steps"]:
        runner = targets.RUNNERS.get(step["kind"])
        if runner is None:
            outcome = m.RunOutcome(status=m.FAILED, reason=m.R_TARGET_MISSING)
            done.append({"kind": step["kind"], "status": m.FAILED, "reason": m.R_TARGET_MISSING})
            break
        outcome = await runner(ctx, _quiet(automation, step), run_row)
        done.append({"kind": step["kind"], "status": outcome.status, "reason": outcome.reason, "report": outcome.report})
        if outcome.cost_usd is not None:
            cost = (cost or 0.0) + outcome.cost_usd
        if outcome.usage is not None:
            usage = {k: (usage or {}).get(k, 0) + outcome.usage[k] for k in ("input", "output", "cache", "total")}
        if outcome.status != m.SUCCEEDED:
            break
    final = outcome.model_copy(update={"report": {"steps": done}, "cost_usd": cost, "usage": usage})
    _tell_once(automation, run_row, final, getattr(ctx, "store", None))
    return final
