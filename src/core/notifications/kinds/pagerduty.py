
from __future__ import annotations

from typing import Any, Dict, Mapping

from src.core.notifications import copy
from src.core.notifications.contracts import SEVERITY_ERROR, SEVERITY_WARN, DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_PAGERDUTY, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_PAGERDUTY)
HOSTS = {"us": "events.pagerduty.com", "eu": "events.eu.pagerduty.com"}
SUMMARY_MAX = 1024
DEDUP_MAX = 255
_SEVERITY = {SEVERITY_ERROR: "error", SEVERITY_WARN: "warning"}


def dedup_key(event: NotifyEvent) -> str:
    instance = event.instance_key or event.toast_id or event.session_id or event.tmux_name or event.session_ref
    return f"{event.type_id}:{instance}"[:DEDUP_MAX]


def build_payload(event: NotifyEvent, config: Mapping[str, Any], routing_key: str) -> Dict[str, Any]:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    payload: Dict[str, Any] = {
        "summary": copy.cap_text(f"{r.title}: {r.body}", SUMMARY_MAX),
        "source": r.computer or "carnivore", "severity": _SEVERITY.get(r.severity, "info"),
    }
    if r.details:
        payload["custom_details"] = {"details": r.details}
    doc: Dict[str, Any] = {"routing_key": routing_key, "event_action": "trigger", "dedup_key": dedup_key(event),
                           "payload": payload}
    if r.link:
        doc["links"] = [{"href": r.link, "text": "open in carnivore"}]
    return doc


class PagerDutySender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        key = secrets.get("routing_key")
        if not isinstance(key, str) or not key:
            return base.invalid("no routing key")
        host = HOSTS["eu" if config.get("region") == "eu" else "us"]
        return await base.post(_SPEC, config, f"https://{host}/v2/enqueue",
                               json_body=build_payload(event, config, key))
