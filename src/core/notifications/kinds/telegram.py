
from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional

from src.core.notifications import copy
from src.core.notifications.destinations.validate import split_list
from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications.kind_specs import KIND_TELEGRAM, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_TELEGRAM)
TEXT_MAX = 4096
_TOKEN = re.compile(r"[0-9]{3,20}:[A-Za-z0-9_-]{20,100}")
_CHAT = re.compile(r"-?[0-9]{1,20}|@[A-Za-z0-9_]{4,64}")


def _override(status: int, body: bytes) -> Optional[FailureClass]:
    if status == 403:
        return FailureClass.GONE
    if status == 404:
        return FailureClass.AUTH
    return None


def build_payload(event: NotifyEvent, config: Mapping[str, Any], chat_id: str) -> dict:
    r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
    return {"chat_id": chat_id, "text": copy.plain_text(r, TEXT_MAX), "link_preview_options": {"is_disabled": True}}


class TelegramSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        token = secrets.get("token")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return base.invalid("bad token")
        chats = split_list(secrets.get("chat_ids"))
        if not chats:
            return base.invalid("no chat ids")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        results: List[DeliveryResult] = []
        for chat in chats:
            if not _CHAT.fullmatch(chat):
                results.append(base.invalid("bad chat id"))
                continue
            results.append(await base.post(_SPEC, config, url, json_body=build_payload(event, config, chat),
                                           override=_override))
        sent = sum(1 for r in results if r.ok)
        if sent == len(results):
            return DeliveryResult(ok=True, status_code=results[-1].status_code)
        if sent:
            return DeliveryResult(ok=True, status_code=200, detail=f"sent {sent} of {len(results)}")
        return next((r for r in results if r.failure is not FailureClass.INVALID), results[0])
