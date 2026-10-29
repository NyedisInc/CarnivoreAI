from __future__ import annotations

import uuid
from typing import Any, Dict

import structlog
from pydantic import ValidationError

from src.core.automations import delivered
from src.core.automations import models as m
from src.core.automations import recipes
from src.core.app_alerts import constants as alert_const
from src.core.app_alerts import service as alert_service

logger = structlog.get_logger()
REPORT_TYPE, FAILED_TYPE = "automation_report", "automation_failed"


def _tell(type_id: str, automation: Dict[str, Any], run_id: str, severity: str, store: Any = None) -> None:
    kind = "failed" if type_id == FAILED_TYPE else "report"
    key = f"automation.{kind}.{run_id}"
    row = alert_service.raise_alert(
        key, source="automations", severity=severity, title_key=f"app_alert.automation.{kind}.title",
        params={"automation": str(automation.get("name") or "")}, auto_resolve=False,
        actions=[{"id": "open", "label_key": "app_alert.automation.open", "href": f"#automations/run/{run_id}"}])
    if row is not None and store is not None:
        try:
            store.update_run(run_id, delivered=delivered.record(kind, key))
        except m.AutomationNotFound:
            pass


def tell_notice(text: str) -> bool:
    row = alert_service.raise_alert(
        f"automation.notice.{uuid.uuid4().hex}", source="automations", severity=alert_const.SEV_INFO,
        title_key="app_alert.automation.notice.title", params={"text": text}, auto_resolve=False,
        actions=[{"id": "open", "label_key": "app_alert.automation.notice.open", "href": "#automations"}])
    return row is not None


def tell_failure(automation: Dict[str, Any], run_id: str, store: Any = None) -> bool:
    delivery = automation.get("delivery") or {}
    if not delivery.get("notify", True) or (delivery.get("notify_on") or "failure") not in ("failure", "always"):
        return False
    _tell(FAILED_TYPE, automation, run_id, alert_const.SEV_WARN, store)
    return True


def _wants(automation: Dict[str, Any], failure: bool) -> bool:
    delivery = automation["delivery"]
    if not delivery.get("notify", True):
        return False
    default = "failure" if automation["target"].get("recipe") in m.SYSTEM_ACTIONS else "report"
    when = delivery.get("notify_on") or default
    return when == "always" or (when == "failure" if failure else when in ("report", "always"))


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
    if _wants(automation, failed):
        _tell(FAILED_TYPE if failed else REPORT_TYPE, automation, run_row["run_id"], alert_const.SEV_WARN if failed else alert_const.SEV_INFO,
              getattr(ctx, "store", None))
    return outcome
