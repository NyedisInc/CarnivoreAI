
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Dict, Mapping

from src.core.notifications import copy
from src.core.notifications.contracts import DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_WEBHOOK, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_WEBHOOK)
SCHEMA_VERSION = 1
_HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,64}")
_RESERVED = {"content-type", "content-length", "host", "x-carnivore-signature", "x-carnivore-delivery"}


def build_body(event: NotifyEvent, config: Mapping[str, Any]) -> bytes:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    doc: Dict[str, Any] = {
        "v": SCHEMA_VERSION, "type": event.type_id, "title": r.title,
        "session": {"name": r.session, "project": r.project}, "computer": r.computer, "link": r.link,
        "ts": event.ts,
    }
    if r.details:
        doc["details"] = r.details
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(body: bytes, signing_secret: str) -> str:
    return "sha256=" + hmac.new(signing_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class WebhookSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        url = secrets.get("url")
        if not isinstance(url, str) or not url:
            return base.invalid("no url")
        body = build_body(event, config)
        headers = {
            "Content-Type": "application/json",
            "X-Carnivore-Delivery": base.delivery_id(event, base.dest_id_of(config)),
        }
        signing = secrets.get("signing_secret")
        if isinstance(signing, str) and signing:
            headers["X-Carnivore-Signature"] = sign(body, signing)
        name, value = config.get("header_name"), secrets.get("header_value")
        if isinstance(name, str) and name and isinstance(value, str) and value:
            if not _HEADER_NAME.fullmatch(name) or name.lower() in _RESERVED or "\r" in value or "\n" in value:
                return base.invalid("bad auth header")
            headers[name] = value
        return await base.post(_SPEC, config, url, content=body, headers=headers)
