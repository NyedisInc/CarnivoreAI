from __future__ import annotations

import uuid
from typing import Any, Dict

import structlog
from pydantic import ValidationError

from src.core.automations import models as m
from src.core.automations import notify_policy
from src.core.automations import recipes
from src.core.app_alerts import constants as alert_const
from src.core.app_alerts import service as alert_service

logger = structlog.get_logger()


def tell_notice(text: str) -> bool:
    row = alert_service.raise_alert(
        f"automation.notice.{uuid.uuid4().hex}", source="automations", severity=alert_const.SEV_INFO,
        title_key="app_alert.automation.notice.title", params={"text": text}, auto_resolve=False,
        actions=[{"id": "open", "label_key": "app_alert.automation.notice.open", "href": "#automations"}])
    return row is not None


def tell_failure(automation: Dict[str, Any], run_id: str, store: Any = None) -> bool:
    if not notify_policy.decide({**automation, "delivery": automation.get("delivery") or {}}, True):
        return False
    notify_policy.tell(notify_policy.FAILED_TYPE, automation, run_id, store)
    return True


async def run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    target = automation["target"]
    found = recipes.lookup(target["recipe"])
    if found is None:
        return m.RunOutcome(status=m.FAILED, reason=m.R_TARGET_MISSING)
    params_model, recipe = found
    try:
        params = params_model.model_validate(target.get("params") or {})
    except ValidationError:
        outcome = m.RunOutcome(status=m.FAILED, reason="params_invalid")
    else:
        try:
            report, cost = await recipe(ctx, params)
            outcome = m.RunOutcome(status=m.SUCCEEDED, report=report, cost_usd=cost)
        except recipes.RecipeFailed as exc:
            outcome = m.RunOutcome(status=m.FAILED, reason=exc.reason)
        except recipes.RecipeSkipped as exc:
            return m.RunOutcome(status=m.SKIPPED, reason=exc.reason)
    failed = outcome.status != m.SUCCEEDED
    notice = notify_policy.decide(automation, failed, notify_policy.default_for_recipe(automation))
    if notice:
        notify_policy.tell(notice, automation, run_row["run_id"], getattr(ctx, "store", None))
    return outcome
