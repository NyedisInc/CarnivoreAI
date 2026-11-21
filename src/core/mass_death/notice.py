
from __future__ import annotations

from src.core.app_alerts import constants as K
from src.core.app_alerts import service
from src.core.mass_death.detector import MassDeathEvent

ALERT_KEY = "sessions.mass_death"
ALERT_SOURCE = "sessions"
RESUME_ROUTE = "/sessions/mass-death/resume"
TITLE_KEY = "app_alert.sessions.mass_death.title"
DETAIL_KEY = "app_alert.sessions.mass_death.detail"
ACTION_LABEL_KEY = "app_alert.action.mass_death_resume"


def raise_for(event: MassDeathEvent) -> None:
    action = {"id": "mass_death_resume", "label_key": ACTION_LABEL_KEY, "method": "POST", "route": RESUME_ROUTE,
              "body": {"session_uuids": list(event.session_uuids)}}
    service.raise_alert(ALERT_KEY, source=ALERT_SOURCE, severity=K.SEV_ERROR, title_key=TITLE_KEY, detail_key=DETAIL_KEY,
                        params={"count": str(event.count), "at": int(event.at)}, actions=(action,))


def resolve() -> None:
    service.resolve(ALERT_KEY)
