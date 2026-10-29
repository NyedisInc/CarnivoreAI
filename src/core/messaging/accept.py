
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional

from src.core.messaging import contract

PROVIDER_DISABLED = "provider_disabled"
NOT_ROUTABLE = "not_routable"
WRONG_CONVERSATION = "wrong_conversation"
WEAK_IDENTITY = "weak_identity"
NOT_OWNER = "not_owner"
NO_INBOUND_BINDING = "no_inbound_binding"
EMPTY = "empty"
RATE_LIMITED = "rate_limited"

INBOUND_PER_HOUR = 60

NOTICE_SMS = "not_imessage"
NOTICE_NOBODY = "nobody_listens"
NOTICE_RATE = "rate_limited"

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_PHONE_FORMATTING = re.compile(r"[\s().\-]")


def normalize_handle(handle: str) -> str:
    value = (handle or "").strip()
    if "@" in value:
        return value.lower()
    digits = _PHONE_FORMATTING.sub("", value)
    if digits.startswith("+") and digits[1:].isdigit():
        return digits
    return digits if digits.isdigit() else value.lower()


def normalize_handles(handles: Iterable[str]) -> FrozenSet[str]:
    return frozenset(h for h in (normalize_handle(x) for x in handles) if h)


def clean_body(text: str) -> str:
    return _CONTROL.sub("", text or "").strip()


@dataclass(frozen=True)
class Verdict:

    reason: Optional[str]
    notice: Optional[str] = None

    @property
    def accepted(self) -> bool:
        return self.reason is None


def is_owner(message: contract.Message, owner_senders: FrozenSet[str]) -> bool:
    return normalize_handle(message.sender) in owner_senders


def accept_received(message: contract.Message, *, enabled: bool, conversation_bound: bool, inbound_bound: bool,
                    owner_senders: FrozenSet[str], recent_inbound: int) -> Verdict:
    if not enabled:
        return Verdict(PROVIDER_DISABLED)
    if message.from_me or message.is_reaction or message.edited:
        return Verdict(NOT_ROUTABLE)
    if not conversation_bound:
        return Verdict(WRONG_CONVERSATION)
    owner = is_owner(message, owner_senders)
    if message.identity != contract.IDENTITY_STRONG:
        return Verdict(WEAK_IDENTITY, NOTICE_SMS if owner else None)
    if not owner:
        return Verdict(NOT_OWNER)
    if not inbound_bound:
        return Verdict(NO_INBOUND_BINDING, NOTICE_NOBODY)
    if not clean_body(message.text) and not message.has_attachments:
        return Verdict(EMPTY)
    if recent_inbound >= INBOUND_PER_HOUR:
        return Verdict(RATE_LIMITED, NOTICE_RATE)
    return Verdict(None)


def accept_supersede(message: contract.Message, *, enabled: bool, conversation_bound: bool,
                     owner_senders: FrozenSet[str]) -> Verdict:
    if not enabled:
        return Verdict(PROVIDER_DISABLED)
    if message.from_me or message.is_reaction:
        return Verdict(NOT_ROUTABLE)
    if not conversation_bound:
        return Verdict(WRONG_CONVERSATION)
    if message.identity != contract.IDENTITY_STRONG:
        return Verdict(WEAK_IDENTITY)
    if not is_owner(message, owner_senders):
        return Verdict(NOT_OWNER)
    return Verdict(None)
