from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from src.core.app_alerts import constants as alert_const
from src.core.app_alerts import service as alert_service
from src.core.automations import delivered
from src.core.automations import models as m

logger = structlog.get_logger()

REPORT_TYPE, FAILED_TYPE = "automation_report", "automation_failed"

DEFAULT_FAILURE = "failure"
DEFAULT_REPORT = "report"
DEFAULT_ALWAYS = "always"

_SEVERITY = {FAILED_TYPE: alert_const.SEV_WARN, REPORT_TYPE: alert_const.SEV_INFO}


def default_for_recipe(automation: Dict[str, Any]) -> str:
    return DEFAULT_FAILURE if automation["target"].get("recipe") in m.SYSTEM_ACTIONS else DEFAULT_REPORT


def decide(automation: Dict[str, Any], failed: bool, default_when: str = DEFAULT_FAILURE) -> Optional[str]:
    delivery = automation["delivery"]
    if not delivery.get("notify", True):
        return None
    when = delivery.get("notify_on") or default_when
    if failed:
        return FAILED_TYPE if when in (DEFAULT_ALWAYS, DEFAULT_FAILURE) else None
    return REPORT_TYPE if when in (DEFAULT_REPORT, DEFAULT_ALWAYS) else None


def tell(type_id: str, automation: Dict[str, Any], run_id: str, store: Any = None) -> None:
    kind = "failed" if type_id == FAILED_TYPE else "report"
    key = f"automation.{kind}.{run_id}"
    row = alert_service.raise_alert(
        key, source="automations", severity=_SEVERITY[type_id], title_key=f"app_alert.automation.{kind}.title",
        params={"automation": str(automation.get("name") or "")}, auto_resolve=False,
        actions=[{"id": "open", "label_key": "app_alert.automation.open", "href": f"#automations/run/{run_id}"}])
    if row is not None and store is not None:
        try:
            store.update_run(run_id, delivered=delivered.record(kind, key))
        except m.AutomationNotFound:
            pass
