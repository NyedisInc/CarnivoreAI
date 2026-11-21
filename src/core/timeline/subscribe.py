
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.timeline import agent_tail, ctx_cache, cursor as cursors, gate, push, rewind, state as state_fields
from src.core.timeline.identity import CONVERSATIONS
from src.core.timeline.model import FILE_KEY_MAIN, Kind, TimelineEvent

log = structlog.get_logger(__name__)

MAX_STATES: int = 256


class PosRef(NamedTuple):

    offset: int
    serial: Optional[str]


@dataclass(frozen=True)
class TimelineBatch:

    session_uuid: Optional[str]
    conv: str
    file_key: str
    from_pos: PosRef
    to_pos: PosRef
    events: Tuple[TimelineEvent, ...] = ()
    state_changed: bool = False
    state: Mapping[str, Any] = field(default_factory=dict)
    reset: Optional[str] = None


Listener = Callable[[TimelineBatch], None]

_listeners: List[Tuple[Optional[frozenset], Listener]] = []
_listeners_lock = threading.Lock()
_states: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_states_lock = threading.Lock()
PUSH = push.FrameCoalescer(resource_push.publish_frame, resource_push.loop_time, resource_push.call_later)


def subscribe(kinds: Optional[Iterable[Kind]], listener: Listener) -> Callable[[], None]:
    entry = (frozenset(kinds) if kinds is not None else None, listener)
    with _listeners_lock:
        _listeners.append(entry)

    def unsubscribe() -> None:
        with _listeners_lock:
            if entry in _listeners:
                _listeners.remove(entry)

    return unsubscribe


def listening() -> bool:
    with _listeners_lock:
        return bool(_listeners)


def _changed_state(conv: str, fields: Mapping[str, Any]) -> Dict[str, Any]:
    with _states_lock:
        before = _states.pop(conv, {})
        _states[conv] = dict(fields)
        while len(_states) > MAX_STATES:
            _states.popitem(last=False)
    return state_fields.changed_fields(before, fields)


def _deliver(batch: TimelineBatch) -> None:
    with _listeners_lock:
        entries = list(_listeners)
    for kinds, listener in entries:
        narrowed = batch if kinds is None else _narrowed(batch, kinds)
        try:
            listener(narrowed)
        except Exception as exc:  # noqa: BLE001
            log.warning("timeline_listener_failed", conv=batch.conv, error=str(exc), error_type=type(exc).__name__)
    if batch.session_uuid is not None:
        PUSH.add(batch.session_uuid, batch.conv, batch.file_key, batch.to_pos, dict(batch.state), batch.reset)


def _narrowed(batch: TimelineBatch, kinds: frozenset) -> TimelineBatch:
    return TimelineBatch(batch.session_uuid, batch.conv, batch.file_key, batch.from_pos, batch.to_pos,
                         tuple(e for e in batch.events if e.kind in kinds), batch.state_changed, batch.state, batch.reset)


def publish(batch: TimelineBatch) -> None:
    if not resource_push.call_on_loop(_deliver, batch):
        _deliver(batch)


def drop_memory() -> None:
    with _states_lock:
        _states.clear()
    CONVERSATIONS.clear()
    ctx_cache.clear()
    cursors.forget_checked()
    rewind.clear()
    agent_tail.TAILS.clear()
    if not resource_push.call_on_loop(PUSH.clear):
        PUSH.clear()


gate.on_off(drop_memory)


def _stop_when_off() -> bool:
    return not gate.hook_on()


def offer_step(conv: str, step: Any, state: Any, facts: Any, reset: Optional[str]) -> None:
    try:
        if _stop_when_off():
            return
        fields = state_fields.transcript_fields(state, facts)
        changed = _changed_state(conv, fields)
        batch = TimelineBatch(CONVERSATIONS.session_of(conv), conv, FILE_KEY_MAIN,
                              PosRef(step.from_offset, step.from_serial), PosRef(step.to_offset, step.to_serial),
                              tuple(step.events), bool(changed), changed, reset)
        publish(batch)
    except Exception as exc:  # noqa: BLE001
        log.error("timeline_offer_failed", conv=conv, error=type(exc).__name__, exc_info=True)


def offer_agent(conv: str, file_key: str, from_pos: PosRef, to_pos: PosRef, events: Iterable[TimelineEvent],
                reset: Optional[str]) -> None:
    try:
        if _stop_when_off():
            return
        publish(TimelineBatch(CONVERSATIONS.session_of(conv), conv, file_key, from_pos, to_pos, tuple(events), False, {}, reset))
    except Exception as exc:  # noqa: BLE001
        log.error("timeline_offer_agent_failed", conv=conv, file_key=file_key, error=type(exc).__name__, exc_info=True)


def reset_for_tests() -> None:
    with _listeners_lock:
        _listeners.clear()
    with _states_lock:
        _states.clear()
    PUSH.clear()
    CONVERSATIONS.clear()
    cursors.forget_checked()
    rewind.clear()
    agent_tail.TAILS.clear()
