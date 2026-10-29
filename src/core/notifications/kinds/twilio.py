
from __future__ import annotations

import re
from typing import Any, Mapping

from src.core.notifications import copy
from src.core.notifications.destinations.validate import split_list
from src.core.notifications.contracts import DeliveryResult, NotifyEvent
from src.core.notifications.kind_specs import KIND_TWILIO, get_kind
from src.core.notifications.kinds import base

_SPEC = get_kind(KIND_TWILIO)
_SID = re.compile(r"[A-Za-z0-9]{10,64}")
_NUMBER = re.compile(r"\+[1-9][0-9]{6,14}")


class TwilioSender:

    async def send(self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> DeliveryResult:
        sid, token, sender = secrets.get("sid"), secrets.get("token"), secrets.get("from_number")
        if not (isinstance(sid, str) and _SID.fullmatch(sid) and isinstance(token, str) and token):
            return base.invalid("bad credentials")
        if not (isinstance(sender, str) and _NUMBER.fullmatch(sender)):
            return base.invalid("bad from number")
        numbers = split_list(secrets.get("numbers"))
        if not numbers:
            return base.invalid("no numbers")
        text = copy.sms_text(copy.render(event, _SPEC, details_on=False))
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        results = []
        for number in numbers:
            if not _NUMBER.fullmatch(number):
                results.append(base.invalid("bad number"))
                continue
            results.append(await base.post(_SPEC, config, url, data={"To": number, "From": sender, "Body": text},
                                           auth=(sid, token)))
        return base.aggregate(results)
