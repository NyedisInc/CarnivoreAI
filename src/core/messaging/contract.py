
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Tuple

CPP_VERSION = 1

EVENT_RECEIVED = "message.received"
EVENT_EDITED = "message.edited"
EVENT_UNSENT = "message.unsent"
EVENT_HEALTH = "provider.health"
KNOWN_EVENTS = frozenset({EVENT_RECEIVED, EVENT_EDITED, EVENT_UNSENT, EVENT_HEALTH})

IDENTITY_NONE = "none"
IDENTITY_WEAK = "weak"
IDENTITY_STRONG = "strong"
_IDENTITIES = frozenset({IDENTITY_NONE, IDENTITY_WEAK, IDENTITY_STRONG})

_SEND_STATUSES = frozenset({"queued", "sent"})

MIN_RETAINED_EVENTS = 1000


class ContractError(ValueError):
    pass


def parse_time(value: Any) -> Optional[float]:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ContractError("time is not a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError("time is not RFC 3339") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _obj(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{what} is not an object")
    return value


def _bool(data: Mapping[str, Any], key: str, default: Optional[bool] = None) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ContractError(f"{key} is not a boolean")
    return value


def _str(data: Mapping[str, Any], key: str, *, required: bool = True, allow_empty: bool = False) -> Optional[str]:
    value = data.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ContractError(f"{key} is not a string")
    return value


def _int(data: Mapping[str, Any], key: str, default: Optional[int] = None) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{key} is not a non-negative integer")
    return value


@dataclass(frozen=True)
class Health:

    send_ready: bool
    receive_ready: bool
    detail: str


@dataclass(frozen=True)
class Capabilities:

    provider: str
    version: str
    send: bool
    receive: bool
    threading: str
    max_identity: str
    max_text_chars: int
    attachments: bool
    stream_ws: bool
    routable_filter: bool
    retained_events: int
    health: Health

    def as_json(self) -> dict:
        return {
            "provider": self.provider, "version": self.version, "send": self.send, "receive": self.receive,
            "threading": self.threading, "max_identity": self.max_identity, "max_text_chars": self.max_text_chars,
            "attachments": self.attachments,
            "stream": {"ws": self.stream_ws, "routable_filter": self.routable_filter,
                       "retained_events": self.retained_events},
            "health": {"send_ready": self.health.send_ready, "receive_ready": self.health.receive_ready,
                       "detail": self.health.detail},
            "retained_warning": self.retained_events < MIN_RETAINED_EVENTS,
        }


def _health(value: Any) -> Health:
    data = _obj(value, "health")
    detail = data.get("detail", "")
    return Health(_bool(data, "send_ready"), _bool(data, "receive_ready"), detail[:200] if isinstance(detail, str) else "")


def parse_capabilities(value: Any) -> Capabilities:
    data = _obj(value, "capabilities")
    if data.get("cpp") != CPP_VERSION:
        raise ContractError("cpp version is not 1")
    threading = data.get("threading", "none")
    if threading not in ("none", "available"):
        raise ContractError("threading is not none or available")
    identity = data.get("max_identity")
    if not isinstance(identity, str) or identity not in _IDENTITIES:
        raise ContractError("max_identity is not none, weak or strong")
    stream = _obj(data.get("stream", {}), "stream")
    max_chars = _int(data, "max_text_chars", 2000)
    if max_chars < 1:
        raise ContractError("max_text_chars is below 1")
    return Capabilities(
        provider=str(_str(data, "provider"))[:80], version=str(_str(data, "version", required=False) or "")[:40],
        send=_bool(data, "send"), receive=_bool(data, "receive"), threading=threading, max_identity=identity,
        max_text_chars=max_chars, attachments=_bool(data, "attachments", False),
        stream_ws=_bool(stream, "ws", False), routable_filter=_bool(stream, "routable_filter", False),
        retained_events=_int(stream, "retained_events", 0), health=_health(data.get("health", {
            "send_ready": False, "receive_ready": False})),
    )


@dataclass(frozen=True)
class ConversationEntry:

    conversation: str
    label: str
    participants: Tuple[str, ...]
    routable: bool


def parse_conversations(value: Any) -> Tuple[ConversationEntry, ...]:
    data = _obj(value, "conversations")
    items = data.get("conversations")
    if not isinstance(items, list):
        raise ContractError("conversations is not a list")
    out = []
    for item in items:
        entry = _obj(item, "conversation")
        people = entry.get("participants", [])
        out.append(ConversationEntry(
            conversation=str(_str(entry, "conversation")), label=str(entry.get("label") or "")[:80],
            participants=tuple(p for p in people if isinstance(p, str)) if isinstance(people, list) else (),
            routable=entry.get("routable") is True,
        ))
    return tuple(out)


@dataclass(frozen=True)
class SendResult:

    message_id: str
    sent_at: Optional[float]
    status: str
    status_ok: bool = True
    replayed: bool = False


def parse_send_result(value: Any) -> SendResult:
    data = _obj(value, "send result")
    try:
        message_id = str(_str(data, "message_id"))[:200]
    except ContractError:
        raise ContractError("send answer has no message_id; the provider may have accepted the send") from None
    status = data.get("status")
    status_ok = isinstance(status, str) and status in _SEND_STATUSES
    try:
        sent_at = parse_time(data.get("sent_at"))
    except ContractError:
        sent_at = None
    return SendResult(message_id, sent_at, status if status_ok else "sent", status_ok)


@dataclass(frozen=True)
class Message:

    message_id: str
    conversation: str
    sender: str
    identity: str
    sent_at: Optional[float]
    in_reply_to: Optional[str]
    text: str
    from_me: bool
    is_reaction: bool
    edited: bool
    has_attachments: bool


@dataclass(frozen=True)
class Event:

    id: int
    type: str
    ts: Optional[float]
    message: Optional[Message] = None
    health: Optional[Health] = None


def _message(value: Any) -> Message:
    data = _obj(value, "message")
    identity = data.get("identity", IDENTITY_NONE)
    if isinstance(identity, (list, dict)):
        raise ContractError("identity is not a string")
    if not isinstance(identity, str) or identity not in _IDENTITIES:
        identity = IDENTITY_NONE
    return Message(
        message_id=str(_str(data, "message_id"))[:200], conversation=str(_str(data, "conversation"))[:400],
        sender=str(_str(data, "sender", allow_empty=True) or "")[:200], identity=identity,
        sent_at=parse_time(data.get("sent_at")), in_reply_to=_str(data, "in_reply_to", required=False),
        text=data["text"] if isinstance(data.get("text"), str) else "",
        from_me=_bool(data, "from_me", False), is_reaction=_bool(data, "is_reaction", False),
        edited=_bool(data, "edited", False), has_attachments=_bool(data, "has_attachments", False),
    )


def parse_event(value: Any) -> Event:
    data = _obj(value, "event")
    event_id = _int(data, "id")
    kind = _str(data, "type")
    ts = parse_time(data.get("ts"))
    if kind in (EVENT_RECEIVED, EVENT_EDITED, EVENT_UNSENT):
        return Event(event_id, str(kind), ts, message=_message(data.get("message")))
    if kind == EVENT_HEALTH:
        return Event(event_id, str(kind), ts, health=_health(data.get("health")))
    return Event(event_id, str(kind), ts)


@dataclass(frozen=True)
class SkippedEvent:

    event_id: Optional[int]
    type: Optional[str]
    reason: str
    salvaged: Optional[Message] = None


def _salvage(value: Any) -> Optional[Message]:
    if not isinstance(value, Mapping):
        return None
    try:
        identity = value.get("identity")
        return Message(
            message_id=str(_str(value, "message_id"))[:200], conversation=str(_str(value, "conversation"))[:400],
            sender=str(_str(value, "sender", allow_empty=True) or "")[:200],
            identity=identity if isinstance(identity, str) and identity in _IDENTITIES else IDENTITY_NONE,
            sent_at=None, in_reply_to=None, text="", from_me=value.get("from_me", False) is not False,
            is_reaction=value.get("is_reaction", False) is not False, edited=True, has_attachments=False)
    except ContractError:
        return None


def parse_event_or_skip(value: Any) -> "Event | SkippedEvent":
    try:
        return parse_event(value)
    except ContractError as exc:
        data = value if isinstance(value, Mapping) else {}
        raw_id, raw_type = data.get("id"), data.get("type")
        event_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id >= 0 else None
        kind = raw_type if isinstance(raw_type, str) else None
        salvaged = _salvage(data.get("message")) if kind in (EVENT_EDITED, EVENT_UNSENT) else None
        return SkippedEvent(event_id, kind, str(exc), salvaged)


@dataclass(frozen=True)
class Hello:

    after: int
    oldest: int
    latest: int
    gap: bool


def parse_hello(value: Any) -> Hello:
    data = _obj(value, "hello")
    if data.get("type") != "hello" or data.get("cpp") != CPP_VERSION:
        raise ContractError("first frame is not a cpp 1 hello")
    return Hello(_int(data, "after"), _int(data, "oldest"), _int(data, "latest"), _bool(data, "gap"))


@dataclass(frozen=True)
class EventsPage:

    events: Tuple["Event | SkippedEvent", ...] = field(default_factory=tuple)
    oldest: int = 0
    latest: int = 0
    gap: bool = False


def parse_events_page(value: Any) -> EventsPage:
    data = _obj(value, "events page")
    items = data.get("events")
    if not isinstance(items, list):
        raise ContractError("events is not a list")
    return EventsPage(tuple(parse_event_or_skip(i) for i in items), _int(data, "oldest"), _int(data, "latest"), _bool(data, "gap"))
