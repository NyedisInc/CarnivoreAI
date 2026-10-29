
from __future__ import annotations

from typing import Any, Mapping

from src.core.notifications import copy
from src.core.notifications.destinations.validate import split_list
from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications.kind_specs import KIND_EMAIL, get_kind
from src.core.notifications.kinds import base, smtp_transport as st

_SPEC = get_kind(KIND_EMAIL)
_MAP = (
    (st.MailBlocked, FailureClass.BLOCKED), (st.MailTimeout, FailureClass.TIMEOUT),
    (st.MailNetworkError, FailureClass.NETWORK), (st.MailAuthError, FailureClass.AUTH),
    (st.MailRejected, FailureClass.INVALID), (st.MailTempFailure, FailureClass.SERVER),
)


def failure_for(exc: st.MailError) -> DeliveryResult:
    for cls, failure in _MAP:
        if isinstance(exc, cls):
            return DeliveryResult(ok=False, failure=failure, detail=exc.reason)
    return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail=exc.reason)


class EmailSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        host = config.get("smtp_host")
        security = config.get("security") or "starttls"
        sender, recipients = secrets.get("from_address"), split_list(secrets.get("recipients"))
        if not (isinstance(host, str) and host and isinstance(sender, str) and sender and recipients):
            return base.invalid("incomplete")
        try:
            port = int(config.get("smtp_port") or 0) or None
        except (TypeError, ValueError):
            return base.invalid("bad port")
        r = copy.render(event, _SPEC, details_on=bool(config.get("details")))
        user, password = secrets.get("user"), secrets.get("password")
        try:
            await st.send_mail(
                host=host, port=port, security=security, username=user if isinstance(user, str) and user else None,
                password=password if isinstance(password, str) and password else None, sender=sender,
                recipients=recipients, subject=r.title, body=copy.plain_text(r), dest_id=base.dest_id_of(config),
            )
        except st.MailError as exc:
            return failure_for(exc)
        return DeliveryResult(ok=True)
