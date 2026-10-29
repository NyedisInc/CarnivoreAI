
from __future__ import annotations

from typing import Any, Mapping

from src.core.notifications import copy
from src.core.notifications.contracts import DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_DISCORD, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_DISCORD)
CONTENT_MAX = 2000
FLAG_SUPPRESS_EMBEDS = 4


def build_payload(event: NotifyEvent, config: Mapping[str, Any]) -> dict:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    parts = [f"**{r.title}**", r.body]
    if r.link:
        parts.append(r.link)
    if r.details:
        parts.append(r.details)
    return {
        "content": copy.cap_text("\n".join(parts), CONTENT_MAX),
        "allowed_mentions": {"parse": []},
        "flags": FLAG_SUPPRESS_EMBEDS,
    }


class DiscordSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        url = secrets.get("url")
        if not isinstance(url, str) or not url:
            return base.invalid("no url")
        return await base.post(_SPEC, config, url, json_body=build_payload(event, config))
