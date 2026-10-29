
from __future__ import annotations

from typing import Any, Mapping

from src.core.notifications import copy
from src.core.notifications.contracts import DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_SLACK, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_SLACK)


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_payload(event: NotifyEvent, config: Mapping[str, Any]) -> dict:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    lines = [f"*{escape(r.title)}*", escape(r.body)]
    if r.link:
        lines.append(f"<{escape(r.link)}|open in carnivore>")
    if r.details:
        lines.append(escape(r.details))
    return {"text": "\n".join(lines), "unfurl_links": False, "unfurl_media": False}


class SlackSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        url = secrets.get("url")
        if not isinstance(url, str) or not url:
            return base.invalid("no url")
        return await base.post(_SPEC, config, url, json_body=build_payload(event, config))
