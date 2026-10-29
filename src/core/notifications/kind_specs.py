
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

DEST_ID_RE = re.compile(r"^d_[0-9a-f]{12}\Z")
WEBPUSH_PREFIX = "webpush:"
APNS_PREFIX = "apns:"

KIND_SLACK = "slack"
KIND_DISCORD = "discord"
KIND_TEAMS = "teams"
KIND_TELEGRAM = "telegram"
KIND_NTFY = "ntfy"
KIND_PUSHOVER = "pushover"
KIND_WEBHOOK = "webhook"
KIND_EMAIL = "email"
KIND_SNS = "sns"
KIND_TWILIO = "twilio"
KIND_PAGERDUTY = "pagerduty"
KIND_WEBPUSH = "webpush"
KIND_APNS = "apns"

FIELD_TEXT = "text"
FIELD_URL = "url"
FIELD_SECRET = "secret"
FIELD_LIST = "list"
FIELD_INT = "int"
FIELD_ENUM = "enum"


@dataclass(frozen=True)
class FieldSpec:

    name: str
    type: str = FIELD_TEXT
    required: bool = True
    secret: bool = False
    max_len: int = 256
    pattern: Optional[str] = None
    choices: Tuple[str, ...] = ()
    default: Optional[str] = None


@dataclass(frozen=True)
class HostRules:

    exact_hosts: Tuple[str, ...] = ()
    suffixes: Tuple[str, ...] = ()
    regex: Optional[str] = None
    any_host: bool = False
    path_prefix: Optional[str] = None


@dataclass(frozen=True)
class KindSpec:

    id: str
    label_key: str
    public_fields: Tuple[FieldSpec, ...] = ()
    secret_fields: Tuple[FieldSpec, ...] = ()
    hosts: HostRules = HostRules()
    allow_private: bool = False
    sms_like: bool = False
    details_allowed: bool = True
    virtual: bool = False


def _secret(name: str, type_: str = FIELD_SECRET, required: bool = True, max_len: int = 512) -> FieldSpec:
    return FieldSpec(name=name, type=type_, required=required, secret=True, max_len=max_len)


def _kind(kind_id: str, **kw: object) -> KindSpec:
    return KindSpec(id=kind_id, label_key=f"notify.kind.{kind_id}", **kw)  # type: ignore[arg-type]


_SMS_NUMBERS = FieldSpec(name="numbers", type=FIELD_LIST, secret=True, max_len=20, pattern=r"\+[1-9][0-9]{6,14}")

KINDS: Tuple[KindSpec, ...] = (
    _kind(KIND_SLACK, secret_fields=(_secret("url", FIELD_URL),),
          hosts=HostRules(exact_hosts=("hooks.slack.com", "hooks.slack-gov.com"))),
    _kind(KIND_DISCORD, secret_fields=(_secret("url", FIELD_URL),),
          hosts=HostRules(exact_hosts=("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com",
                                       "ptb.discordapp.com", "canary.discordapp.com"),
                          path_prefix="/api/webhooks/")),
    _kind(KIND_TEAMS, secret_fields=(_secret("url", FIELD_URL),),
          hosts=HostRules(suffixes=(".logic.azure.com", ".api.powerplatform.com"))),
    _kind(KIND_TELEGRAM, secret_fields=(_secret("token"), _secret("chat_ids", FIELD_LIST)),
          hosts=HostRules(exact_hosts=("api.telegram.org",))),
    _kind(KIND_NTFY,
          public_fields=(FieldSpec(name="base_url", type=FIELD_URL, required=False, default="https://ntfy.sh"),),
          secret_fields=(_secret("topic"), _secret("token", required=False)),
          hosts=HostRules(exact_hosts=("ntfy.sh",), any_host=True), allow_private=True),
    _kind(KIND_PUSHOVER, secret_fields=(_secret("app_token"), _secret("user_key")),
          hosts=HostRules(exact_hosts=("api.pushover.net",))),
    _kind(KIND_WEBHOOK,
          public_fields=(FieldSpec(name="header_name", required=False, max_len=64, pattern=r"[A-Za-z0-9-]+"),),
          secret_fields=(_secret("url", FIELD_URL), _secret("signing_secret", required=False),
                         _secret("header_value", required=False)),
          hosts=HostRules(any_host=True), allow_private=True),
    _kind(KIND_EMAIL,
          public_fields=(FieldSpec(name="smtp_host", max_len=253),
                         FieldSpec(name="smtp_port", type=FIELD_INT, default="587"),
                         FieldSpec(name="security", type=FIELD_ENUM, choices=("starttls", "tls", "plain"),
                                   default="starttls")),
          secret_fields=(_secret("user", required=False), _secret("password", required=False),
                         _secret("from_address"), _secret("recipients", FIELD_LIST)),
          hosts=HostRules(any_host=True)),
    _kind(KIND_SNS,
          public_fields=(FieldSpec(name="region", type=FIELD_ENUM, max_len=32,
                                   pattern=r"[a-z]{2}(?:-[a-z]+)+-[0-9]"),),
          secret_fields=(_secret("key_id"), _secret("secret_key"), _secret("session_token", required=False),
                         _SMS_NUMBERS),
          hosts=HostRules(regex=r"sns\.[a-z]{2}(?:-[a-z]+)+-[0-9]\.amazonaws\.com"),
          sms_like=True, details_allowed=False),
    _kind(KIND_TWILIO,
          secret_fields=(_secret("sid"), _secret("token"), _secret("from_number"), _SMS_NUMBERS),
          hosts=HostRules(exact_hosts=("api.twilio.com",)), sms_like=True, details_allowed=False),
    _kind(KIND_PAGERDUTY,
          public_fields=(FieldSpec(name="region", type=FIELD_ENUM, choices=("us", "eu"), default="us"),),
          secret_fields=(_secret("routing_key"),),
          hosts=HostRules(exact_hosts=("events.pagerduty.com", "events.eu.pagerduty.com"))),
    _kind(KIND_WEBPUSH, hosts=HostRules(any_host=True), details_allowed=False, virtual=True),
    _kind(KIND_APNS, hosts=HostRules(exact_hosts=("api.carnivore.ai",)), details_allowed=False, virtual=True),
)

_BY_ID: Dict[str, KindSpec] = {k.id: k for k in KINDS}


def get_kind(kind_id: str) -> Optional[KindSpec]:
    return _BY_ID.get(kind_id)


def ordered_kinds() -> List[KindSpec]:
    return list(KINDS)


def is_destination_id(value: object) -> bool:
    return isinstance(value, str) and DEST_ID_RE.match(value) is not None


def new_destination_id() -> str:
    return "d_" + secrets.token_hex(6)


def webpush_destination_id(subscription_id: str) -> str:
    return WEBPUSH_PREFIX + subscription_id


def is_webpush_destination_id(value: object) -> bool:
    return isinstance(value, str) and value.startswith(WEBPUSH_PREFIX) and len(value) > len(WEBPUSH_PREFIX)


def apns_destination_id(device_row_id: str) -> str:
    return APNS_PREFIX + device_row_id


def is_apns_destination_id(value: object) -> bool:
    return isinstance(value, str) and value.startswith(APNS_PREFIX) and len(value) > len(APNS_PREFIX)


def is_push_destination_id(value: object) -> bool:
    return is_webpush_destination_id(value) or is_apns_destination_id(value)


def virtual_kind_of(dest_id: object) -> Optional[str]:
    if is_webpush_destination_id(dest_id):
        return KIND_WEBPUSH
    return KIND_APNS if is_apns_destination_id(dest_id) else None
