
from __future__ import annotations

import threading
from typing import Dict, Optional

from src.core.notifications.contracts import Sender
from src.core.notifications.kind_specs import (
    KIND_DISCORD, KIND_EMAIL, KIND_NTFY, KIND_PAGERDUTY, KIND_PUSHOVER, KIND_SLACK, KIND_SNS, KIND_TEAMS,
    KIND_TELEGRAM, KIND_TWILIO, KIND_WEBHOOK, KIND_WEBPUSH, KIND_APNS,
)
from src.core.notifications.kinds.discord import DiscordSender
from src.core.notifications.kinds.mail import EmailSender
from src.core.notifications.kinds.ntfy import NtfySender
from src.core.notifications.kinds.pagerduty import PagerDutySender
from src.core.notifications.kinds.pushover import PushoverSender
from src.core.notifications.kinds.slack import SlackSender
from src.core.notifications.kinds.sns import SnsSender
from src.core.notifications.kinds.teams import TeamsSender
from src.core.notifications.kinds.telegram import TelegramSender
from src.core.notifications.kinds.twilio import TwilioSender
from src.core.notifications.kinds.webhook import WebhookSender
from src.core.notifications.kinds.apns import ApnsKindSender
from src.core.notifications.kinds.webpush import WebPushSender

_LOCK = threading.RLock()
_SENDERS: Dict[str, Sender] = {}


def register(kind_id: str, sender: Sender) -> None:
    with _LOCK:
        _SENDERS[kind_id] = sender


def unregister(kind_id: str) -> bool:
    with _LOCK:
        return _SENDERS.pop(kind_id, None) is not None


def unregister_prefix(prefix: str) -> int:
    with _LOCK:
        victims = [k for k in _SENDERS if k.startswith(prefix)]
        for k in victims:
            _SENDERS.pop(k, None)
        return len(victims)


def sender_for(kind_id: str) -> Optional[Sender]:
    with _LOCK:
        return _SENDERS.get(kind_id)


register(KIND_SLACK, SlackSender())
register(KIND_DISCORD, DiscordSender())
register(KIND_TEAMS, TeamsSender())
register(KIND_TELEGRAM, TelegramSender())
register(KIND_WEBHOOK, WebhookSender())
register(KIND_NTFY, NtfySender())
register(KIND_PUSHOVER, PushoverSender())
register(KIND_PAGERDUTY, PagerDutySender())
register(KIND_EMAIL, EmailSender())
register(KIND_SNS, SnsSender())
register(KIND_TWILIO, TwilioSender())
register(KIND_WEBPUSH, WebPushSender())
register(KIND_APNS, ApnsKindSender())
