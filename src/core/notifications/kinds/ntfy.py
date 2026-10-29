
from __future__ import annotations

import base64
from typing import Any, Dict, Mapping
from urllib.parse import quote

from src.core.notifications import copy
from src.core.notifications.contracts import SEVERITY_ERROR, SEVERITY_WARN, DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_NTFY, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_NTFY)
DEFAULT_BASE = "https://ntfy.sh"
_PRIORITY = {SEVERITY_ERROR: "5", SEVERITY_WARN: "4"}
_TAGS = {SEVERITY_ERROR: "rotating_light", SEVERITY_WARN: "warning"}


def header_value(text: str) -> str:
    clean = " ".join(text.split())
    try:
        clean.encode("ascii")
        return clean
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(clean.encode("utf-8")).decode("ascii") + "?="


def build_request(event: NotifyEvent, config: Mapping[str, Any]) -> tuple[Dict[str, str], bytes]:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    headers = {"Title": header_value(r.title), "Priority": _PRIORITY.get(r.severity, "3"),
               "Tags": "carnivore" + (f",{_TAGS[r.severity]}" if r.severity in _TAGS else "")}
    if r.link:
        headers["Click"] = header_value(r.link)
    text = r.body + (f"\n{r.details}" if r.details else "")
    return headers, text.encode("utf-8")


class NtfySender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        topic = secrets.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            return base.invalid("no topic")
        root = config.get("base_url") or DEFAULT_BASE
        if not isinstance(root, str) or not root.startswith(("https://", "http://")):
            return base.invalid("bad base url")
        headers, body = build_request(event, config)
        token = secrets.get("token")
        if isinstance(token, str) and token:
            if "\r" in token or "\n" in token:
                return base.invalid("bad token")
            headers["Authorization"] = f"Bearer {token}"
        url = f"{root.rstrip('/')}/{quote(topic.strip(), safe='')}"
        return await base.post(_SPEC, config, url, content=body, headers=headers)
