
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.core import db
from src.core.swarm import push, store, thread_port
from src.core.swarm.definition import UPPER_RANKS
from src.core.swarm.names import shown_name

logger = structlog.get_logger()

AGENT_WAKING = "agent_waking"
WAKING_WINDOW_S = 120
WAKING_CODES = frozenset({"pane_not_an_agent", "session_gone", "session_not_found"})
TRUST_PREFIX = "trust:"
HELD_PREFIX = "held:"
IMPORT_PREFIX = "import:"
CHOICE_PREFIX = "choice:"
STUCK_PREFIX = "stuck:"
_DIALOG_LINE_CHARS = 200


def _conn() -> sqlite3.Connection:
    from src.config import settings

    return db.connect(db.db_path_for(settings.get_state_dir()), create=False)


def _parse(stamp: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
    except ValueError:
        return None


def is_waking(agent: Dict[str, Any], wake: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> bool:
    if agent.get("state") == "waking":
        return True
    started = _parse(wake.get("started_at")) if wake else None
    clock = now or datetime.now(timezone.utc)
    return agent.get("state") == "awake" and started is not None and clock - started < timedelta(seconds=WAKING_WINDOW_S)


def classify(code: str, *, waking: bool) -> str:
    return AGENT_WAKING if waking and code in WAKING_CODES else code


def waking_for_thread(thread_key: str) -> bool:
    try:
        with closing(_conn()) as conn:
            agent = store.get_agent_by_thread_key(conn, thread_key)
            return bool(agent) and is_waking(agent, store.get_open_wake(conn, agent["id"]))
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_waking_unreadable", error_type=type(exc).__name__)
        return False


def record(agent_id: int, authority: str, source: str, source_ref: Optional[str] = None,
           owner_message_ref: Optional[str] = None) -> int:
    with closing(_conn()) as conn:
        wake = store.get_open_wake(conn, agent_id)
        return store.record_delivery(conn, agent_id, authority=authority, source=source,
                                     wake_id=wake["id"] if wake else None, source_ref=source_ref,
                                     owner_message_ref=owner_message_ref)


def discard(delivery_id: int) -> None:
    try:
        with closing(_conn()) as conn:
            store.delete_delivery(conn, delivery_id)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_delivery_discard_failed", delivery_id=delivery_id, error_type=type(exc).__name__)


_BEFORE_WRITE = frozenset({"session_not_found", "pane_dialog_open", "pane_not_an_agent", "session_gone",
                           "receiver_instance_changed", "paste_unsupported"})


def nothing_landed(exc: HTTPException) -> bool:
    if exc.status_code == 404:
        return True
    detail = exc.detail
    return exc.status_code == 409 and isinstance(detail, dict) and detail.get("code") in _BEFORE_WRITE


def record_for_key(session_uuid: str, source: str, source_ref: str) -> Optional[int]:
    with closing(_conn()) as conn:
        agent = store.get_agent_by_session_uuid(conn, session_uuid)
        if agent is None:
            return None
        wake = store.get_open_wake(conn, agent["id"])
        return store.record_delivery(conn, agent["id"], authority="data", source=source,
                                     wake_id=wake["id"] if wake else None, source_ref=source_ref)


def is_swarm_body(session_row_id: Optional[int]) -> bool:
    if session_row_id is None:
        return False
    with closing(_conn()) as conn:
        return store.get_agent_by_session_row(conn, session_row_id) is not None


def is_delivery_of_body(session_row_id: Optional[int], delivery_id: int) -> bool:
    if session_row_id is None:
        return False
    with closing(_conn()) as conn:
        return conn.execute(
            "SELECT 1 FROM swarm_deliveries d JOIN swarm_agents a ON a.id = d.agent_id WHERE d.id = ? AND a.session_row_id = ?",
            (delivery_id, session_row_id)).fetchone() is not None


async def record_for_paste(request: Any, session_id: str, source_ref: str) -> Optional[int]:
    info = await request.app.state.session_manager.get_session_info(session_id=session_id)
    try:
        return await asyncio.to_thread(record_for_session_row, getattr(info, "session_row_id", None), "send_message", source_ref)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError):
        raise HTTPException(status_code=503, detail={"code": "swarm_record_failed",
                                                     "detail": "the Swarm could not record who sent this; nothing was pasted"}) from None


async def paste_as_data(request: Any, session_id: str, text: str, source_ref: str, *,
                        send: Optional[Callable[..., Awaitable[Any]]] = None, **gates: Any) -> Any:
    from src.api.one_shot_routes import paste_through_gates

    row = await record_for_paste(request, session_id, source_ref)
    try:
        return await (send or paste_through_gates)(request, session_id, text, **gates)
    except HTTPException as exc:
        if row is not None and nothing_landed(exc):
            await asyncio.to_thread(discard, row)
        raise


def record_for_session_row(session_row_id: Optional[int], source: str, source_ref: str) -> Optional[int]:
    if session_row_id is None:
        return None
    with closing(_conn()) as conn:
        agent = store.get_agent_by_session_row(conn, session_row_id)
        if agent is None:
            return None
        wake = store.get_open_wake(conn, agent["id"])
        return store.record_delivery(conn, agent["id"], authority="data", source=source,
                                     wake_id=wake["id"] if wake else None, source_ref=source_ref)


def trust_ref(wake_id: int, fingerprint: str) -> str:
    return f"{TRUST_PREFIX}{wake_id}:{fingerprint}"


async def post_trust_card(agent: Dict[str, Any], wake_id: int, fingerprint: str) -> Optional[int]:
    port = thread_port.get()
    if port is None:
        return None
    ref = trust_ref(wake_id, fingerprint)
    async with _dialog_card_lock:
        reused = await port.open_card_id(agent["thread_key"], ref)
        if reused is not None:
            _trust_card_at.setdefault((wake_id, fingerprint), datetime.now(timezone.utc))
            return reused
        await port.close_open_cards(agent["thread_key"], TRUST_PREFIX)
        where = agent["repo_dir"]
        text = (f"{shown_name(agent)} is starting in {where}. Claude Code asks whether you trust this folder. "
                "trust it, or not now to leave it asleep.")
        item_id = await port.post_card(agent["thread_key"], "question", "trust this folder?", text, ref)
        _trust_card_at[(wake_id, fingerprint)] = datetime.now(timezone.utc)
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])
    return item_id



RETRY_S = 2.0
QUEUE_S = 1800.0
WAKE_PROMPT_S = 300.0
_BUSY = frozenset({"pane_dialog_open", "paste_not_settled"})

_locks: Dict[int, "asyncio.Lock"] = {}
_pending: Dict[int, int] = {}
_tasks: set = set()
_trust_posted: set = set()
_trust_card_at: Dict[Tuple[int, str], datetime] = {}
_trust_auto_tries: Dict[Tuple[int, str], int] = {}
_trust_auto_at: Dict[Tuple[int, str], datetime] = {}
_trust_carried_since: Dict[Tuple[int, str], float] = {}
AUTO_TRUST_TRIES = 3
AUTO_TRUST_CONFIRM_S = 2.5
AUTO_TRUST_POLL_S = 0.25
_dialog_posted: set = set()
_dialog_card_lock = asyncio.Lock()


def _shim(app_state: Any) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=app_state))


def _code(exc: HTTPException) -> str:
    detail = exc.detail
    return str(detail.get("code") or "refused") if isinstance(detail, dict) else "refused"


def _lock(agent_id: int) -> "asyncio.Lock":
    return _locks.setdefault(agent_id, asyncio.Lock())


def _spawn(coro: Any) -> None:
    async def guarded() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except (HTTPException, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            logger.warning("swarm_delivery_task_failed", error_type=type(exc).__name__, error=str(exc)[:300])

    task = asyncio.get_running_loop().create_task(guarded())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _dialog(app_state: Any, session_id: str) -> Optional[Any]:
    watcher = getattr(app_state, "attention_watcher", None)
    seen = watcher.observation_for(session_id) if watcher is not None else None
    return seen.evidence.dialog if seen is not None else None


def _dialog_prefix(dialog: Any) -> str:
    from src.core.approvals.extract import KIND_OTHER, KIND_TRUST

    said = " ".join(f"{dialog.question} {dialog.body}".lower().split())
    if dialog.kind == KIND_TRUST:
        return TRUST_PREFIX
    if "held message" in said:
        return HELD_PREFIX
    if "external" in said and "import" in said:
        return IMPORT_PREFIX
    if dialog.kind == KIND_OTHER and _option_label(dialog, "yes") and _option_label(dialog, "no") and len(dialog.rows) == 2:
        return CHOICE_PREFIX
    return STUCK_PREFIX


_BORDER_CHARS = {c: " " for c in range(0x2500, 0x25A0)}


def _plain(text: str) -> str:
    lines = (ln.translate(_BORDER_CHARS).strip() for ln in (text or "").splitlines())
    return " ".join(" ".join(ln for ln in lines if any(ch.isalnum() for ch in ln)).split())


def _dialog_line(dialog: Any) -> str:
    from src.core.mcp.tools import redact_text

    question = _plain(dialog.question)
    first = next((ln for ln in (_plain(ln) for ln in (dialog.body or "").splitlines()) if ln and ln != question), "")
    return redact_text(" ".join(f"{question} {first}".split()))[:_DIALOG_LINE_CHARS]


NO_ONLY = ":no"


def choice_is_no_only(agent: Dict[str, Any], dialog: Any) -> bool:
    from src.core.approvals.extract import enables_browser_tools

    return agent["rank"] in UPPER_RANKS and enables_browser_tools(dialog)


def _choice_text(who: str, dialog: Any, no_only: bool) -> str:
    from src.core.approvals.extract import ROLE_OPTION
    from src.core.mcp.tools import redact_text

    heading = redact_text(_plain(dialog.question))[:_DIALOG_LINE_CHARS]
    rows = [f'"{redact_text(r.label.strip()).lower()}"' for r in dialog.rows if r.role == ROLE_OPTION]
    head = f"{who} is stopped on a startup prompt in its terminal: {heading}."
    if no_only:
        no = next((r for r in rows if r.startswith('"no')), rows[0])
        return f"{head} {who} never gets browser tools, so the one choice offered is {no}; nothing is answered for you."
    return f"{head} the choices are {' and '.join(rows)}; nothing is answered for you."


async def post_dialog_card(agent: Dict[str, Any], prefix: str, fingerprint: str, dialog: Any) -> Optional[int]:
    port = thread_port.get()
    if port is None:
        return None
    no_only = prefix == CHOICE_PREFIX and choice_is_no_only(agent, dialog)
    ref = f"{prefix}{agent['id']}:{fingerprint}{NO_ONLY if no_only else ''}"
    async with _dialog_card_lock:
        reused = await port.open_card_id(agent["thread_key"], ref)
        if reused is not None:
            return reused
        return await _post_dialog_card(port, agent, prefix, ref, dialog)


async def _post_dialog_card(port: Any, agent: Dict[str, Any], prefix: str, ref: str, dialog: Any) -> int:
    await port.close_open_cards(agent["thread_key"], prefix)
    line, who = _dialog_line(dialog), shown_name(agent)
    if prefix == HELD_PREFIX:
        card = ("question", "deliver a held message?", f"Claude Code is holding a message for {who} from another session ({line}). "
                "deliver it, or deny it.")
    elif prefix == IMPORT_PREFIX:
        card = ("question", "allow external imports?", f"{who} is asking Claude Code whether a CLAUDE.md may import files from outside "
                f"its folder ({line}). allow it, or deny it to keep imports disabled.")
    elif prefix == CHOICE_PREFIX:
        card = ("question", "answer a startup prompt?", _choice_text(who, dialog, ref.endswith(NO_ONLY)))
    else:
        card = ("info", "stuck on a dialog", f"{who} is stuck on a dialog in its terminal: {line}")
    item_id = await port.post_card(agent["thread_key"], card[0], card[1], card[2], ref)
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])
    return item_id


async def _maybe_dialog_card(app_state: Any, agent: Dict[str, Any], wake_id: Optional[int], info: Any) -> None:
    from src.core.approvals.auto_answer.engine import answers_own_dev_channels

    dialog = await _dialog(app_state, info.session.id)
    if dialog is None or answers_own_dev_channels(dialog):
        return
    prefix = _dialog_prefix(dialog)
    if prefix == TRUST_PREFIX:
        if wake_id is None or (wake_id, dialog.fingerprint) in _trust_posted:
            return
        if await _auto_trust(app_state, agent, wake_id, info, dialog):
            return
        _trust_posted.add((wake_id, dialog.fingerprint))
        await post_trust_card(agent, wake_id, dialog.fingerprint)
        return
    key = (agent["id"], dialog.fingerprint)
    if key in _dialog_posted:
        return
    _dialog_posted.add(key)
    await post_dialog_card(agent, prefix, dialog.fingerprint, dialog)


def has_dialog_cards(agent_id: int) -> bool:
    return any(owner == agent_id for owner, _ in _dialog_posted)


async def close_gone_dialog_cards(agent: Dict[str, Any]) -> None:
    port = thread_port.get()
    if port is None:
        return
    for prefix in (CHOICE_PREFIX, HELD_PREFIX, IMPORT_PREFIX, STUCK_PREFIX):
        await port.close_open_cards(agent["thread_key"], prefix)
    _dialog_posted.difference_update({key for key in _dialog_posted if key[0] == agent["id"]})


def forget_wake(wake_id: int) -> None:
    for table in (_trust_card_at, _trust_auto_tries, _trust_auto_at, _trust_carried_since):
        for key in [key for key in table if key[0] == wake_id]:
            del table[key]
    _trust_posted.difference_update({key for key in _trust_posted if key[0] == wake_id})


async def wake_ended(agent: Dict[str, Any], wake_id: int) -> None:
    forget_wake(wake_id)
    await close_wake_trust_cards(agent)


async def close_wake_trust_cards(agent: Dict[str, Any]) -> None:
    port = thread_port.get()
    if port is not None:
        await port.close_open_cards(agent["thread_key"], TRUST_PREFIX)


async def _past_trust_gate(app_state: Any, agent: Dict[str, Any], wake_id: int) -> bool:
    from src.core.swarm import body

    info = await body.live_info(app_state, agent)
    if info is None or getattr(info, "startup_gate", None) != "ready":
        return False
    watcher = getattr(app_state, "attention_watcher", None)
    seen = watcher.observation_for(info.session.id) if watcher is not None else None
    if seen is None or getattr(seen, "stale", False) or seen.evidence.dialog is not None:
        return False
    posted = [at for (wake, _), at in _trust_card_at.items() if wake == wake_id]
    try:
        return not posted or seen.observed_at > max(posted)
    except (TypeError, AttributeError):
        return False


async def close_gone_trust_cards(app_state: Any, agent: Dict[str, Any], wake_id: int) -> bool:
    pending = any(wake == wake_id for wake, _ in _trust_card_at)
    port = thread_port.get()
    if port is None:
        return True
    if not await _past_trust_gate(app_state, agent, wake_id):
        return not pending
    await port.close_open_cards(agent["thread_key"], TRUST_PREFIX)
    for key in [key for key in _trust_card_at if key[0] == wake_id]:
        del _trust_card_at[key]
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])
    return True


async def _config_dir_name(app_state: Any, info: Any) -> str:
    from src.core.account_switch.pane_account import read_pane_profile

    manager = getattr(app_state, "session_manager", None)
    if manager is None or not getattr(info, "tmux_session", None):
        return "unknown"
    seen = await read_pane_profile(manager.tmux_socket_name(), str(info.tmux_session), "CLAUDE_CONFIG_DIR")
    return os.path.basename(seen.value.rstrip("/")) if seen.readable and seen.value else "default"


async def _auto_trust(app_state: Any, agent: Dict[str, Any], wake_id: int, info: Any, dialog: Any) -> bool:
    from src.core.swarm import auto_trust, body

    key = (wake_id, dialog.fingerprint)
    tries = _trust_auto_tries.get(key, 0)
    wake = await body.run_db(lambda c: store.get_open_wake(c, agent["id"]))
    if wake is None or wake["id"] != wake_id:
        return False
    if not await body.run_db(lambda c: auto_trust.may_auto_answer(c, agent, wake, info, dialog)):
        first = _trust_carried_since.setdefault(key, time.monotonic())
        return time.monotonic() - first <= auto_trust.CARRIED_WAIT_SECONDS and await body.run_db(
            lambda c: auto_trust.may_auto_answer(c, agent, wake, info, dialog, allow_unmeasured=True))
    label = _yes_label(dialog)
    if label is None:
        return False
    if tries >= AUTO_TRUST_TRIES:
        return False
    answered_at = _trust_auto_at.get(key)
    if answered_at is not None:
        watcher = getattr(app_state, "attention_watcher", None)
        seen = watcher.observation_for(info.session.id) if watcher is not None else None
        try:
            if seen is None or not seen.observed_at > answered_at + timedelta(seconds=AUTO_TRUST_CONFIRM_S):
                return True
        except (TypeError, AttributeError):
            return False
        _trust_auto_tries[key] = AUTO_TRUST_TRIES
        return False
    _trust_auto_tries[key] = tries + 1
    try:
        await _send_answer(app_state, info.session.id, dialog.fingerprint, label)
    except body.BodyError as exc:
        logger.info("swarm_trust_auto_refused", agent_id=agent["id"], wake_id=wake_id, fingerprint=dialog.fingerprint, reason=str(exc)[:200])
        return True
    _trust_auto_at[key] = answered_at = datetime.now(timezone.utc)
    logger.info("swarm_trust_auto_answered", agent_id=agent["id"], wake_id=wake_id, folder=os.path.realpath(str(info.session.working_dir)),
                config_dir=await _config_dir_name(app_state, info), fingerprint=dialog.fingerprint)
    if await _answer_took(app_state, info.session.id, dialog.fingerprint, answered_at):
        return True
    _trust_auto_tries[key] = AUTO_TRUST_TRIES
    return False


async def _answer_took(app_state: Any, session_id: str, fingerprint: str, answered_at: datetime) -> bool:
    deadline = asyncio.get_running_loop().time() + AUTO_TRUST_CONFIRM_S
    watcher = getattr(app_state, "attention_watcher", None)
    still_there = False
    while True:
        tick = getattr(watcher, "tick_sessions", None)
        if tick is not None:
            try:
                await asyncio.wait_for(tick({session_id}), timeout=max(deadline - asyncio.get_running_loop().time(), 0.01))
            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                logger.warning("swarm_trust_confirm_tick_failed", session_id=session_id, error=str(exc)[:200])
        seen = watcher.observation_for(session_id) if watcher is not None else None
        try:
            if seen is not None and not getattr(seen, "stale", False) and seen.observed_at > answered_at:
                dialog = seen.evidence.dialog
                still_there = dialog is not None and dialog.fingerprint == fingerprint
                if not still_there:
                    return True
        except (TypeError, AttributeError):
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return not still_there
        await asyncio.sleep(AUTO_TRUST_POLL_S)


async def _attempt(app_state: Any, agent_id: int, text: str, source: str, authority: str, source_ref: Optional[str],
                   owner_message_ref: Optional[str]) -> Tuple[str, Optional[str]]:
    from src.api.one_shot_routes import paste_through_gates
    from src.core.mcp.common import ToolError
    from src.core.swarm import body, reply_mirror

    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if agent is None or agent["torn_down_at"] is not None or agent["state"] in ("asleep", "sleeping"):
        return "failed", "asleep"
    if source == "wake_prompt" and source_ref and await body.run_db(lambda c: kickoff_recorded(c, agent_id, source_ref)):
        return "delivered", None
    wake = await body.run_db(lambda c: store.get_open_wake(c, agent_id))
    waking = is_waking(agent, wake)
    info = await body.live_info(app_state, agent)
    if info is None:
        return ("retry", AGENT_WAKING) if waking else ("failed", "session_gone")
    if getattr(info, "startup_gate", None) == "awaiting_startup_prompt":
        await _maybe_dialog_card(app_state, agent, wake["id"] if wake else None, info)
        return "retry", AGENT_WAKING
    if wake:
        await close_gone_trust_cards(app_state, agent, wake["id"])
    row = await asyncio.to_thread(record, agent_id, authority, source, source_ref, owner_message_ref)
    if authority == "owner" and owner_message_ref and source in reply_mirror.SOURCES:
        reply_mirror.note_owner_delivery(agent_id)
    try:
        if agent.get("host_key", "local") != "local":
            from src.core.pack.span import remote_body

            await remote_body.paste(info, text)
        else:
            await paste_through_gates(_shim(app_state), info.session.id, text)
    except ToolError as exc:
        await asyncio.to_thread(discard, row)
        return "retry", AGENT_WAKING
    except HTTPException as exc:
        if nothing_landed(exc):
            await asyncio.to_thread(discard, row)
        code = classify(_code(exc), waking=waking)
        if code in ("pane_dialog_open", AGENT_WAKING):
            await _maybe_dialog_card(app_state, agent, wake["id"] if wake else None, info)
        return ("retry", code) if code == AGENT_WAKING or code in _BUSY else ("failed", code)
    return "delivered", None


async def _retry(app_state: Any, agent_id: int, text: str, source: str, authority: str, source_ref: Optional[str],
                 owner_message_ref: Optional[str], window_s: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + window_s
    try:
        while loop.time() < deadline:
            await asyncio.sleep(RETRY_S)
            async with _lock(agent_id):
                state, code = await _attempt(app_state, agent_id, text, source, authority, source_ref, owner_message_ref)
            if state == "delivered":
                return
            if state == "failed":
                logger.warning("swarm_delivery_dropped", agent_id=agent_id, source=source, code=code)
                return
        logger.info("swarm_delivery_expired", agent_id=agent_id, source=source)
    finally:
        _pending[agent_id] = max(0, _pending.get(agent_id, 1) - 1)


async def deliver_text(app_state: Any, agent_id: int, text: str, *, source: str, authority: str,
                       source_ref: Optional[str] = None, owner_message_ref: Optional[str] = None,
                       window_s: float = QUEUE_S) -> str:
    args = (app_state, agent_id, text, source, authority, source_ref, owner_message_ref)
    if not _pending.get(agent_id):
        async with _lock(agent_id):
            state, code = await _attempt(*args)
        if state == "delivered":
            return "delivered"
        if state == "failed":
            logger.warning("swarm_delivery_refused", agent_id=agent_id, source=source, code=code)
            return f"refused:{code}"
    else:
        code = AGENT_WAKING if await asyncio.to_thread(waking_for_agent, agent_id) else "pane_dialog_open"
    _pending[agent_id] = _pending.get(agent_id, 0) + 1
    _spawn(_retry(*args, window_s))
    return "waking" if code == AGENT_WAKING else "held"


def waking_for_agent(agent_id: int) -> bool:
    try:
        with closing(_conn()) as conn:
            agent = store.get_agent(conn, agent_id)
            return bool(agent) and is_waking(agent, store.get_open_wake(conn, agent_id))
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError):
        return False


def kickoff_recorded(conn: sqlite3.Connection, agent_id: int, wake_ref: str) -> bool:
    return conn.execute("SELECT 1 FROM swarm_deliveries WHERE agent_id = ? AND source = 'wake_prompt' AND source_ref = ? LIMIT 1",
                        (agent_id, wake_ref)).fetchone() is not None


KICKOFF_GRACE_S = 20.0


async def settle_wake(app_state: Any, agent_id: int) -> bool:
    from src.core.swarm import body

    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    wake = await body.run_db(lambda c: store.get_open_wake(c, agent_id)) if agent else None
    if agent is None or agent["torn_down_at"] is not None or agent["state"] != "awake":
        return True
    await close_gone_dialog_cards(agent)
    if wake is None:
        return True
    if not await close_gone_trust_cards(app_state, agent, wake["id"]):
        return False
    started = _parse(wake.get("started_at"))
    if _pending.get(agent_id) or started is None or (datetime.now(timezone.utc) - started).total_seconds() < KICKOFF_GRACE_S:
        return False
    if await body.run_db(lambda c: kickoff_recorded(c, agent_id, f"wake:{wake['id']}")):
        return True
    logger.info("swarm_kickoff_recovered", agent_id=agent_id, wake_id=wake["id"])
    send_wake_prompt(app_state, agent, wake["id"], wake["mode"] or "fresh", wake["reason"] or "manual", "", "data", None)
    return True


def send_wake_prompt(app_state: Any, agent: Dict[str, Any], wake_id: int, mode: str, reason: str, orders: str,
                     authority: str, owner_message_ref: Optional[str]) -> None:
    async def run() -> None:
        from src.config import settings as app_settings
        from src.core.swarm import body, desk, learning, settings as swarm_settings, wake_prompt
        from src.core.swarm.memory import SwarmFileError

        try:
            if mode == "fresh":
                work = await body.run_db(lambda c: desk.gather(c, agent))
                path = await asyncio.to_thread(wake_prompt.write_desk, app_settings.get_state_dir(), agent, reason, orders, work)
                text, inbox = wake_prompt.fresh_message(path), work.learning
            else:
                inbox = await body.run_db(lambda c: learning.queued(c, agent["id"]))
                text = await asyncio.to_thread(lambda: wake_prompt.resume_message(reason, orders, agent, inbox, swarm_settings.naming_family_on()))
            await body.run_db(lambda c: learning.mark_delivered(c, [i["id"] for i in inbox], wake_id))
        except (SwarmFileError, OSError, sqlite3.Error, db.DatastoreUnreadableError) as exc:
            logger.warning("swarm_wake_prompt_not_written", agent_id=agent["id"], error_type=type(exc).__name__)
            return
        owner = authority == "owner" and owner_message_ref is not None
        await deliver_text(app_state, agent["id"], text, source="wake_prompt", authority="owner" if owner else "data",
                           source_ref=f"wake:{wake_id}", owner_message_ref=owner_message_ref if owner else None,
                           window_s=WAKE_PROMPT_S)

    _spawn(run())



def _yes_label(dialog: Any) -> Optional[str]:
    from src.core.approvals.extract import ROLE_OPTION

    return next((r.label for r in dialog.rows if r.role == ROLE_OPTION and r.label.strip().lower().startswith("yes")), None)


async def _send_answer(app_state: Any, session_id: str, fingerprint: str, label: str) -> None:
    from src.api.session_dialog_routes import answer_session_dialog
    from src.core.swarm import body
    from src.models.dialogs import AnswerChoice, DialogAnswerRequest

    try:
        await answer_session_dialog(_shim(app_state), session_id,
                                    DialogAnswerRequest(fingerprint=fingerprint, choice=AnswerChoice(option=label)))
    except HTTPException as exc:
        raise body.BodyError(f"the dialog was not answered: {exc.detail}") from exc


async def answer_trust(app_state: Any, swarm_ref: str, approve: bool) -> None:
    from src.core.swarm import body

    _, wake_id, fingerprint = swarm_ref.split(":", 2)
    owner = await body.run_db(lambda c: c.execute("SELECT agent_id FROM swarm_wakes WHERE id = ?", (int(wake_id),)).fetchone())
    if owner is None:
        raise body.BodyError("that trust card belongs to a wake that no longer exists")
    agent_id = int(owner[0])
    if not approve:
        await body.sleep(app_state, agent_id, "failed")
        return
    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    info = await body.live_info(app_state, agent) if agent else None
    dialog = await _dialog(app_state, info.session.id) if info else None
    label = _yes_label(dialog) if dialog is not None else None
    if dialog is None or label is None or dialog.fingerprint != fingerprint:
        if agent is not None and dialog is not None:
            _trust_posted.add((int(wake_id), dialog.fingerprint))
            await post_trust_card(agent, int(wake_id), dialog.fingerprint)
        raise body.BodyError("the folder question changed or is gone; the card was posted again")
    await _send_answer(app_state, info.session.id, fingerprint, label)


def _option_label(dialog: Any, *starts: str) -> Optional[str]:
    from src.core.approvals.extract import ROLE_OPTION

    return next((r.label for r in dialog.rows if r.role == ROLE_OPTION and r.label.strip().lower().startswith(starts)), None)


async def answer_dialog_card(app_state: Any, swarm_ref: str, approve: bool) -> None:
    from src.core.swarm import body

    prefix, raw_id, rest = swarm_ref.split(":", 2)
    fingerprint = rest.split(":", 1)[0]
    agent = await body.run_db(lambda c: store.get_agent(c, int(raw_id)))
    info = await body.live_info(app_state, agent) if agent else None
    dialog = await _dialog(app_state, info.session.id) if info else None
    if approve and f"{prefix}:" == CHOICE_PREFIX and agent is not None and dialog is not None and choice_is_no_only(agent, dialog):
        raise body.BodyError(f"{agent['display_name']} never gets browser tools, so only the no option can be answered; nothing was sent")
    _dialog_posted.discard((int(raw_id), fingerprint))
    yes, no = (("deliver",), ("deny",)) if f"{prefix}:" == HELD_PREFIX else (("yes",), ("no",))
    label = _option_label(dialog, *(yes if approve else no)) if dialog is not None else None
    if dialog is None or label is None or dialog.fingerprint != fingerprint:
        if agent is not None and info is not None:
            await _maybe_dialog_card(app_state, agent, None, info)
        raise body.BodyError("the dialog changed or is gone; the card was posted again")
    await _send_answer(app_state, info.session.id, fingerprint, label)
