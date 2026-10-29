
from __future__ import annotations

from typing import Any, Dict, Mapping

from src.core.notifications import copy
from src.core.notifications.contracts import SEVERITY_ERROR, SEVERITY_WARN, DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_PUSHOVER, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_PUSHOVER)
URL = "https://api.pushover.net/1/messages.json"
MESSAGE_MAX = 1024
TITLE_MAX = 250
_PRIORITY = {SEVERITY_ERROR: "1", SEVERITY_WARN: "1"}


def build_form(event: NotifyEvent, config: Mapping[str, Any], token: str, user: str) -> Dict[str, str]:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    form = {
        "token": token, "user": user, "title": copy.cap_text(r.title, TITLE_MAX),
        "message": copy.cap_text(r.body + (f"\n{r.details}" if r.details else ""), MESSAGE_MAX),
        "priority": _PRIORITY.get(r.severity, "0"),
    }
    if r.link:
        form["url"], form["url_title"] = r.link, "open in carnivore"
    return form


class PushoverSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        token, user = secrets.get("app_token"), secrets.get("user_key")
        if not (isinstance(token, str) and token and isinstance(user, str) and user):
            return base.invalid("no keys")
        return await base.post(_SPEC, config, URL, data=build_form(event, config, token, user))
