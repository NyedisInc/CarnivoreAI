
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote

import structlog

from src.core.notifications import copy, links
from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications.kind_specs import KIND_WEBPUSH, WEBPUSH_PREFIX, get_kind
from src.core.notifications.kinds import base
from src.core.web_push.sender import PushSender

log = structlog.get_logger(__name__)
_SPEC = get_kind(KIND_WEBPUSH)
_provider: Optional[Callable[[], Optional[PushSender]]] = None


def install_push_sender(provider: Optional[Callable[[], Optional[PushSender]]]) -> None:
    global _provider
    _provider = provider


_ASK_TYPES = frozenset({"session.question", "session.permission", "session.plan_approval"})


def build_payload(event: NotifyEvent) -> dict:
    r = copy.render(event, _SPEC, details_on=False)
    if event.type_id in _ASK_TYPES and event.session_id:
        return {"title": r.title, "body": r.body, "path": f"/?approvals={quote(event.session_id, safe='')}"}
    slug = event.tmux_name or event.session_ref
    return {"title": r.title, "body": r.body, "path": links.session_path(slug) if slug else "/"}


class WebPushSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        dest = base.dest_id_of(config)
        sub_id = dest[len(WEBPUSH_PREFIX):] if dest.startswith(WEBPUSH_PREFIX) else ""
        sender = _provider() if _provider else None
        if not sub_id or sender is None:
            return base.invalid("no subscription" if sender else "no push sender")
        status = await sender.send_typed(sub_id, event.type_id, build_payload(event),
                                         event.session_id or event.instance_key or "")
        if status is None:
            return DeliveryResult(ok=False, failure=FailureClass.GONE, detail="no subscription")
        if 200 <= status < 300:
            return DeliveryResult(ok=True, status_code=status)
        if status == 0:
            return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail="no answer")
        result = base.classify(base.GuardResponse(status, {}, b"", False))
        log.info("notify_send_failed", dest_id=dest, kind=KIND_WEBPUSH, failure=result.failure.value, status=status)
        return result
