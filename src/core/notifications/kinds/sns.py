
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping
from urllib.parse import urlencode

from src.core.notifications import copy
from src.core.notifications.destinations.validate import split_list
from src.core.notifications.contracts import DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_SNS, get_kind
from src.core.notifications.kinds import base, sigv4

_SPEC = get_kind(KIND_SNS)
_REGION = re.compile(r"[a-z]{2}(?:-[a-z]+)+-[0-9]")
_NUMBER = re.compile(r"\+[1-9][0-9]{6,14}")
CONTENT_TYPE = "application/x-www-form-urlencoded; charset=utf-8"
clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def build_body(number: str, text: str) -> bytes:
    return urlencode({
        "Action": "Publish", "Version": "2010-03-31", "PhoneNumber": number, "Message": text,
        "MessageAttributes.entry.1.Name": "AWS.SNS.SMS.SMSType",
        "MessageAttributes.entry.1.Value.DataType": "String",
        "MessageAttributes.entry.1.Value.StringValue": "Transactional",
    }).encode("utf-8")


class SnsSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        region = config.get("region")
        if not (isinstance(region, str) and _REGION.fullmatch(region)):
            return base.invalid("bad region")
        key_id, secret = secrets.get("key_id"), secrets.get("secret_key")
        if not (isinstance(key_id, str) and key_id and isinstance(secret, str) and secret):
            return base.invalid("bad credentials")
        token = secrets.get("session_token")
        numbers = split_list(secrets.get("numbers"))
        if not numbers:
            return base.invalid("no numbers")
        text = copy.sms_text(copy.render(event, _SPEC, details_on=False))
        host = f"sns.{region}.amazonaws.com"
        results = []
        for number in numbers:
            if not _NUMBER.fullmatch(number):
                results.append(base.invalid("bad number"))
                continue
            body = build_body(number, text)
            headers: Dict[str, str] = sigv4.sign_v4(
                method="POST", host=host, headers={"Content-Type": CONTENT_TYPE}, body=body, access_key=key_id,
                secret_key=secret, region=region, service="sns",
                session_token=token if isinstance(token, str) and token else None, clock=clock,
            )
            results.append(await base.post(_SPEC, config, f"https://{host}/", content=body, headers=headers))
        return base.aggregate(results)
