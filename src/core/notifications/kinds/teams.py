
from __future__ import annotations

from typing import Any, Mapping

from src.core.notifications import copy
from src.core.notifications.contracts import DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_TEAMS, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_TEAMS)
CARD_VERSION = "1.2"


def build_payload(event: NotifyEvent, config: Mapping[str, Any]) -> dict:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    body = [
        {"type": "TextBlock", "text": r.title, "weight": "Bolder", "size": "Medium", "wrap": True},
        {"type": "TextBlock", "text": r.body, "wrap": True},
    ]
    if r.details:
        body.append({"type": "TextBlock", "text": r.details, "wrap": True, "isSubtle": True})
    card: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": CARD_VERSION,
        "body": body,
    }
    if r.link:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "open in carnivore", "url": r.link}]
    return {
        "type": "message",
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
                         "content": card}],
    }


class TeamsSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        url = secrets.get("url")
        if not isinstance(url, str) or not url:
            return base.invalid("no url")
        return await base.post(_SPEC, config, url, json_body=build_payload(event, config))
