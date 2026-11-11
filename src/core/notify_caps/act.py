
from __future__ import annotations

import asyncio
import hashlib
import time
import weakref
from typing import Any, Callable, Dict, Optional, Tuple

import structlog
from pydantic import ValidationError

from src.core.approvals.answer import AnswerRefused, Choice
from src.core.approvals.deliver import SOURCE_OWNER_PHONE, deliver_answer
from src.core.attention.evidence import STATE_BUSY
from src.core.attention.fresh_observation import watcher_of
from src.core.notify_caps import effects
from src.core.notify_caps.store import CapRecord, CapStore, hash_cap
from src.core.notify_caps.verify import ask_is_open, verify
from src.models.dialogs import AnswerChoice

logger = structlog.get_logger()

Result = Tuple[int, Dict[str, Any]]
Record = Callable[[int, Dict[str, Any]], None]

SETTLE_WAIT_SECONDS = 4.0
SETTLE_POLL_SECONDS = 0.2
TEXT_ACTIONS = frozenset({"reply", "answer"})
GONE_REASONS = frozenset({"no_dialog", "dialog_changed", "session_gone", "not_running"})

_LOCKS: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


def _lock_for(digest: str) -> asyncio.Lock:
    lock = _LOCKS.get(digest)
    if lock is None:
        lock = _LOCKS[digest] = asyncio.Lock()
    return lock


def _choice(action: str, labels: Dict[str, str], text: Optional[str]) -> Optional[Choice]:
    try:
        if action in ("yes", "no"):
            return Choice(plain=action)
        if action.startswith("opt."):
            return Choice(option=AnswerChoice(option=labels[action]).option)
        if action == "reply" and text:
            return Choice(other=AnswerChoice(other=text).other)
    except (ValidationError, KeyError):
        return None
    return None


async def _working_after(watcher: Any, session_id: str, before: int) -> bool:
    if watcher is None:
        return False
    deadline = time.monotonic() + SETTLE_WAIT_SECONDS
    while True:
        seen = watcher.observation_for(session_id)
        if seen is not None and not seen.stale and seen.revision > before:
            return seen.verdict.state == STATE_BUSY
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(SETTLE_POLL_SECONDS)


def _press_key(action: str, text: Optional[str]) -> str:
    if action in TEXT_ACTIONS:
        return f"{action}#{hashlib.sha256((text or '').encode()).hexdigest()[:16]}"
    return action


def _stored(record: CapRecord, key: str) -> Result:
    if record.used_action != key or record.result is None:
        return 409, {"error": "already_used"}
    status, body = int(record.result["status"]), dict(record.result["body"])
    return status, ({**body, "replay": True} if status == 200 else body)


class _SentFlag:

    def __init__(self, manager: Any) -> None:
        self._manager, self.sent = manager, False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)

    async def send_input(self, *args: Any, **kwargs: Any) -> Any:
        self.sent = True
        return await self._manager.send_input(*args, **kwargs)


async def _answer_dialog(app_state: Any, record: CapRecord, choice: Choice, done: Record) -> Tuple[int, Dict[str, Any], bool]:
    target = record.target
    session_id = str(target.get("session", ""))
    if effects.is_remote(session_id):
        wire = {k: v for k, v in (("plain", choice.plain), ("option", choice.option), ("other", choice.other)) if v}
        return (*await effects.forward_dialog(session_id, str(target.get("fingerprint", "")), wire), True)
    manager = app_state.session_manager
    info = await manager.get_session_info(session_id)
    if info is None:
        return 409, {"error": "already_answered", "where": "elsewhere"}, True
    watcher = watcher_of(manager)
    seen = watcher.observation_for(info.session.id) if watcher is not None else None
    before = seen.revision if seen is not None else -1
    tracked = _SentFlag(manager)
    try:
        await deliver_answer(manager=tracked, watcher=watcher, info=info, fingerprint=str(target.get("fingerprint", "")),
                             choice=choice, source=SOURCE_OWNER_PHONE)
    except AnswerRefused as exc:
        if exc.reason in GONE_REASONS:
            return 409, {"error": "already_answered", "where": "elsewhere"}, True
        return 409, {"error": "refused", "reason": exc.reason}, tracked.sent
    except BaseException:
        if tracked.sent:
            done(409, {"error": "refused", "reason": "unconfirmed"})
        raise
    agent = str(record.card.get("agent") or info.label or info.tmux_session or "")
    sent = {"state": "sent", "agent": agent, "working": False}
    done(200, sent)
    return 200, {**sent, "working": await _working_after(watcher, info.session.id, before)}, True


EFFECT_ACTIONS = {"send": frozenset({"reply"}), "reopen": frozenset({"reopen"}), "app_update": frozenset({"install"}),
                  "swarm": frozenset({"pick.1", "pick.2", "answer"}), "agent_update": frozenset({"restart_agents"})}


def _swarm_text(record: CapRecord, action: str, text: Optional[str]) -> str:
    if action == "answer":
        return text or ""
    positions = record.card.get("positions") or []
    index = int(action.split(".")[1]) - 1
    return str(positions[index][1]) if 0 <= index < len(positions) else ""


async def _run_effect(app_state: Any, record: CapRecord, action: str, text: Optional[str], done: Record) -> Optional[Result]:
    target = record.target
    kind = target.get("type")
    session_id = str(target.get("session", ""))
    if action not in EFFECT_ACTIONS.get(str(kind), ()) or action not in record.actions:
        return None
    if kind == "reopen":
        return await effects.reopen(app_state, session_id)
    if kind == "app_update":
        return await effects.install_app_update()
    if kind == "agent_update":
        status, body = await effects.restart_agents(app_state, target.get("sessions"))
        return status, ({**body, "agent": str(record.card.get("agent") or "")} if status == 200 else body)
    if kind == "swarm":
        return await effects.swarm_answer(app_state, target.get("question"), _swarm_text(record, action, text))
    watcher = None if effects.is_remote(session_id) else watcher_of(app_state.session_manager)
    seen = watcher.observation_for(session_id) if watcher is not None else None
    before = seen.revision if seen is not None else -1
    status, body = await effects.send_reply(app_state, session_id, text or "", target.get("thread"))
    if status == 200:
        done(status, body)
        body = {**body, "agent": str(record.card.get("agent") or ""), "working": await _working_after(watcher, session_id, before)}
    return status, body


async def act(store: CapStore, app_state: Any, cap: str, action: str, text: Optional[str],
              now: Optional[float] = None) -> Result:
    record, refused = verify(store, app_state, cap, now)
    if record is None:
        return refused  # type: ignore[return-value]
    async with _lock_for(record.cap_sha256):
        record = store.find(cap) or record
        if record.used_at is not None:
            return _stored(record, _press_key(action, text))
        label_ok = action in record.actions and (action not in TEXT_ACTIONS or bool(text))
        is_dialog = record.target.get("type") == "dialog"
        choice = _choice(action, record.actions, text) if label_ok and is_dialog else None
        effect_ok = label_ok and not is_dialog and action in EFFECT_ACTIONS.get(str(record.target.get("type")), ())
        if effect_ok and record.target.get("type") == "swarm" and not _swarm_text(record, action, text):
            effect_ok = False
        if choice is None and not effect_ok:
            return 422, {"error": "bad_action"}
        gone = await ask_is_open(app_state, record)
        if gone is not None:
            return gone
        digest = hash_cap(cap)
        if not store.reserve(digest, _press_key(action, text), now):
            return 409, {"error": "already_used"}

        def done(code: int, payload: Dict[str, Any]) -> None:
            store.finish(digest, {"status": code, "body": payload})

        consumed = True
        try:
            if choice is not None:
                status, body, consumed = await _answer_dialog(app_state, record, choice, done)
            else:
                status, body = await _run_effect(app_state, record, action, text, done)  # type: ignore[misc]
        except BaseException:
            store.release(digest)
            raise
        if not consumed:
            store.release(digest)
            return status, body
        done(status, body)
        logger.info("notify_cap_acted", cap=digest[:8], action=action, status=status)
        return status, body
