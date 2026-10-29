
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

import structlog

from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications.kind_specs import APNS_PREFIX, KIND_APNS
from src.core.notifications.kinds import base
from src.core.notifications.kinds.webpush import build_payload

log = structlog.get_logger(__name__)
_provider: Optional[Callable[[], Any]] = None


def install_apns_sender(provider: Optional[Callable[[], Any]]) -> None:
    global _provider
    _provider = provider


class ApnsKindSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        dest = base.dest_id_of(config)
        row_id = dest[len(APNS_PREFIX):] if dest.startswith(APNS_PREFIX) else ""
        sender = _provider() if _provider else None
        if not row_id or sender is None:
            return base.invalid("no device" if sender else "no apns sender")
        status = await sender.send_typed(row_id, event.type_id, build_payload(event),
                                         event.session_id or event.instance_key or "")
        if status is None:
            return DeliveryResult(ok=False, failure=FailureClass.GONE, detail="no device")
        if 200 <= status < 300:
            return DeliveryResult(ok=True, status_code=status)
        if status == 0:
            return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail="no answer")
        result = base.classify(base.GuardResponse(status, {}, b"", False))
        log.info("notify_send_failed", dest_id=dest, kind=KIND_APNS, failure=result.failure.value, status=status)
        return result
