
from __future__ import annotations

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

_SENDERS: Dict[str, Sender] = {}


def register(kind_id: str, sender: Sender) -> None:
    _SENDERS[kind_id] = sender


def sender_for(kind_id: str) -> Optional[Sender]:
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
