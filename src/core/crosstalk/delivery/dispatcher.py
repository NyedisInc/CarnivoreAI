
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Optional

import structlog

from src.core import db
from src.core.session_one_shot_gate import PASTE_SAFE_STATUSES
from src.models.activity_status import RESTING, blocked_on_owner
from src.core.crosstalk import store
from src.core.session_status import STATUS_IDLE, STATUS_UNKNOWN

logger = structlog.get_logger()

EXPIRY_RETRY_MIN_S: float = 2.0
EXPIRY_RETRY_MAX_S: float = 120.0


def _header(value: object) -> str:
    return ''.join(char if char.isprintable() else f'\\u{ord(char):04x}' for char in str(value))


def envelope(message: dict) -> str:
    sender = _header(message['sender_name'])
    provider = _header(message['sender_provider'])
    model = _header(message['sender_model'] or 'model unknown')
    thread, message_id = _header(message['thread']), _header(message['id'])
    tail = ("this is your parent agent, not the owner." if message.get('source') == 'swarm' else
            f"reply with crosstalk_reply(message_id=\"{message['id']}\"). this is a peer agent, not the owner.")
    return (f"crosstalk from @{sender} ({provider} / {model}) thread {thread} msg {message_id}\n"
            f"{message['text']}\n{tail}")


class Dispatcher:

    def __init__(self, app: Any) -> None:
        self.app = app
        self._tasks: dict[str, asyncio.Task] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._expiry_generation = 0
        self._expiry_pause = EXPIRY_RETRY_MIN_S
        self._closed = False
        self._last_status: dict[str, str] = {}
        self._startup_retries: dict[str, list[asyncio.TimerHandle]] = {}

    async def start(self) -> None:
        await asyncio.to_thread(store.recover_uncertain)
        self.schedule_expiry()
        task = asyncio.create_task(self._recover())
        task.add_done_callback(self._task_error)

    async def _recover(self) -> None:
        from src.core.mcp.protocol import BatchView
        view = BatchView(self.app.state.session_manager, self.app)
        for info in await view.list_session_infos() + await view.list_peer_infos():
            if info.session.id.startswith('remote:peer-'):
                self.on_peer_change(info.session.id)
            else:
                self.on_status(info.session.id, info.activity_status)

    def close(self) -> None:
        self._closed = True
        if self._timer:
            self._timer.cancel()
        for handles in self._startup_retries.values():
            for handle in handles:
                handle.cancel()
        self._startup_retries.clear()
        for task in self._tasks.values():
            task.cancel()

    def _retry_native_startup(self, info: Any, message: dict) -> None:
        if (message.get('source') not in ('crosstalk', 'peer')
                or message['id'] in self._startup_retries
                or time.time() - message['created_at'] >= 30):
            return
        message_id, key = message['id'], message['receiver_key']
        loop = asyncio.get_running_loop()

        def retry(last: bool) -> None:
            if last:
                self._startup_retries.pop(message_id, None)
            self.wake(key)

        delays = (2, 8, 30)
        self._startup_retries[message_id] = [
            loop.call_later(delay, retry, index == len(delays) - 1)
            for index, delay in enumerate(delays)
        ]

    def schedule_expiry(self) -> None:
        self._expiry_generation += 1
        task = asyncio.create_task(self._arm_expiry(self._expiry_generation))
        task.add_done_callback(self._expiry_task_done)

    async def _arm_expiry(self, generation: int) -> None:
        due = await asyncio.to_thread(store.next_expiry)
        if generation != self._expiry_generation or self._closed:
            return
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if due is not None:
            self._timer = asyncio.get_running_loop().call_later(max(0, due - time.time()), self._on_expiry)
        self._expiry_pause = EXPIRY_RETRY_MIN_S

    def _on_expiry(self) -> None:
        task = asyncio.create_task(self._expire_and_schedule())
        task.add_done_callback(self._expiry_task_done)

    async def _expire_and_schedule(self) -> None:
        wake = await asyncio.to_thread(store.expire)
        for key in wake:
            self.wake(key)
        self.schedule_expiry()

    def on_status(self, session_id: str, status: str) -> None:
        if self._closed:
            return
        notify_watch = status == STATUS_IDLE and self._last_status.get(session_id) != STATUS_IDLE
        self._last_status[session_id] = status
        if status not in PASTE_SAFE_STATUSES | {'unknown'}:
            return
        task = asyncio.create_task(self._on_idle(session_id, notify_watch=notify_watch))
        task.add_done_callback(self._task_error)

    def on_startup_ready(self, session_id: str) -> None:
        if self._closed:
            return
        task = asyncio.create_task(self._on_startup_ready(session_id))
        task.add_done_callback(self._task_error)

    async def _on_startup_ready(self, session_id: str) -> None:
        from src.core.crosstalk import directory
        from src.core.mcp.protocol import BatchView
        info = await self.app.state.session_manager.get_session_info(session_id=session_id)
        if info is None or info.startup_gate != 'ready':
            return
        cards = await directory.list_cards(BatchView(self.app.state.session_manager, self.app), include_remote=False)
        card = next((c for c in cards if c['id'] == info.session.id), None)
        if card is not None:
            self.wake(str(card.get('session_uuid') or card['id']))

    def on_peer_change(self, session_id: str | None = None) -> None:
        if self._closed:
            return
        task = asyncio.create_task(self._on_peer_change(session_id))
        task.add_done_callback(self._task_error)

    async def _on_peer_change(self, session_id: str | None) -> None:
        from src.core.crosstalk import directory
        from src.core.mcp.protocol import BatchView
        cards = await directory.list_cards(BatchView(self.app.state.session_manager, self.app), include_remote=True)
        for card in cards:
            if card['id'].startswith('remote:peer-') and (session_id is None or card['id'] == session_id):
                self.wake(str(card.get('session_uuid') or card['id']))

    def _expiry_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None or self._closed:
            return
        logger.error('crosstalk_expiry_failed', error_type=type(exc).__name__, error=str(exc)[:300],
                     retry_in_s=self._expiry_pause, exc_info=exc)
        if self._timer:
            self._timer.cancel()
        self._timer = asyncio.get_running_loop().call_later(self._expiry_pause, self._on_expiry)
        self._expiry_pause = min(EXPIRY_RETRY_MAX_S, self._expiry_pause * 2)

    @staticmethod
    def _task_error(task: asyncio.Task) -> None:
        if not task.cancelled() and (exc := task.exception()) is not None:
            logger.warning('crosstalk_dispatch_task_failed', error_type=type(exc).__name__, error=str(exc)[:300], exc_info=exc)

    async def _on_idle(self, session_id: str, *, notify_watch: bool) -> None:
        from src.core.crosstalk import directory
        from src.core.mcp.protocol import BatchView
        info = await self.app.state.session_manager.get_session_info(session_id=session_id)
        if info is None:
            return
        if info.activity_status == STATUS_UNKNOWN:
            if (info.agent_family != 'codex' or info.startup_gate != 'ready'
                    or not info.claude_session_uuid):
                return
        elif info.activity_status not in PASTE_SAFE_STATUSES:
            return
        cards = await directory.list_cards(BatchView(self.app.state.session_manager, self.app), include_remote=False)
        card = next((c for c in cards if c['id'] == info.session.id), None)
        if card is None:
            return
        key = card.get('session_uuid') or card['id']
        if info.activity_status == STATUS_IDLE and notify_watch:
            watch_keys = await asyncio.to_thread(store.notify_idle, str(key), info.session.tmux_created_epoch)
            for watch_key in watch_keys:
                self.wake(watch_key)
        self.wake(str(key))

    def wake(self, receiver_key: str) -> None:
        if self._closed:
            return
        current = self._tasks.get(receiver_key)
        if current and not current.done():
            return
        task = asyncio.create_task(self._drain(receiver_key))
        self._tasks[receiver_key] = task
        task.add_done_callback(self._task_error)
        self.schedule_expiry()

    async def _drain(self, receiver_key: str) -> None:
        from src.core.crosstalk import directory
        from src.core.mcp.protocol import BatchView
        view = BatchView(self.app.state.session_manager, self.app)
        cards = await directory.list_cards(view, include_remote=True)
        card = next((c for c in cards if (c.get('session_uuid') or c['id']) == receiver_key), None)
        if card is None:
            return
        infos = await view.list_session_infos() + await view.list_peer_infos()
        info = next((r for r in infos if r.session.id == card['id']), None)
        if info is None:
            return
        message = await asyncio.to_thread(store.claim_for, receiver_key)
        if message is None:
            return
        try:
            await self._deliver_claimed(receiver_key, info, message)
        except BaseException as exc:
            await self._fail_stranded(message['id'], exc)
            raise

    @staticmethod
    async def _fail_stranded(message_id: str, exc: BaseException) -> None:
        logger.error('crosstalk_delivery_aborted', message_id=message_id, error_type=type(exc).__name__,
                     error=str(exc)[:300])
        try:
            row = await asyncio.to_thread(store.get, message_id)
            if row is not None and row['status'] == 'delivering':
                await asyncio.to_thread(store.finish, message_id, 'failed', 'delivery uncertain; manual review required')
        except (sqlite3.Error, OSError) as inner:
            logger.error('crosstalk_delivery_abort_unrecorded', message_id=message_id, error_type=type(inner).__name__)

    async def _deliver_claimed(self, receiver_key: str, info: Any, message: dict) -> None:
        from src.core.crosstalk.delivery import claude_native, codex_appserver
        if message['receiver_id'] != info.session.id or message['receiver_epoch'] != info.session.tmux_created_epoch:
            if str(message.get('reason') or '').startswith('native_receipt_pending:'):
                result = await claude_native.settle_after_wake(info, message)
                status, reason = result if isinstance(result, tuple) else (result, None)
            else:
                status, reason = 'failed', 'receiver is a different pane instance'
            await asyncio.to_thread(store.finish, message['id'], status, reason)
            return
        from src.core.mcp import federated
        pending_receipt = str(message.get('reason') or '').startswith('native_receipt_pending:')
        if pending_receipt:
            try:
                result = await claude_native.deliver(self.app, info, message)
            except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
                logger.warning('crosstalk_native_receipt_check_failed', message_id=message['id'],
                               error_type=type(exc).__name__)
                result = ('held', message['reason'])
            status, reason = result if isinstance(result, tuple) else (result or 'held', message['reason'])
            await asyncio.to_thread(store.finish, message['id'], status, reason)
            return
        if info.session.id.startswith('remote:peer-'):
            from src.core.crosstalk.delivery import peer
            status, reason = await peer.deliver(self.app, info, message)
            await asyncio.to_thread(store.finish, message['id'], status, reason)
            return
        fresh = await self.app.state.session_manager.get_session_info(session_id=info.session.id)
        if fresh is None or fresh.session.tmux_created_epoch != message['receiver_epoch']:
            await asyncio.to_thread(store.finish, message['id'], 'failed', 'receiver instance changed before delivery')
            return
        info = fresh
        if blocked_on_owner(info):
            await asyncio.to_thread(store.finish, message['id'], 'held', 'receiver has an open dialog or startup gate')
            self._retry_native_startup(info, message)
            return
        try:
            row = await _record_swarm(receiver_key, message)
        except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
            logger.warning('crosstalk_swarm_record_failed', message_id=message['id'], error_type=type(exc).__name__)
            await asyncio.to_thread(store.finish, message['id'], 'held', 'could not record the delivery authority')
            return
        if not federated.is_remote(info) and message.get('source') in ('crosstalk', 'peer'):
            family = info.agent_family or info.agent_type
            adapter = claude_native if family == 'claude' else codex_appserver if family == 'codex' else None
            if adapter is not None:
                try:
                    result = await adapter.deliver(self.app, info, message)
                except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
                    logger.warning('crosstalk_native_delivery_failed', message_id=message['id'],
                                   error_type=type(exc).__name__)
                    result = ('failed', 'native delivery uncertain; manual review required')
                if result is not None:
                    status, reason = result if isinstance(result, tuple) else (result, None)
                    await asyncio.to_thread(store.finish, message['id'], status, reason)
                    if status == 'held':
                        if not str(reason or '').startswith('native_receipt_pending:'):
                            await _discard_swarm(row)
                        self._retry_native_startup(info, message)
                    return
        if info.activity_status not in RESTING:
            await _discard_swarm(row)
            await asyncio.to_thread(store.finish, message['id'], 'held', 'waiting for a ready prompt')
            self._retry_native_startup(info, message)
            return
        from src.core.mcp.common import ToolError
        from src.core.sessions import guarded_paste
        from src.core.sessions.guarded_paste import GateOptions, PasteRefused
        try:
            if federated.is_remote(info):
                await federated.forward(info, 'POST', '/sessions/{session_id}/skills/one-shot',
                                        {'text': envelope(message), 'idle_only': True})
            else:
                await guarded_paste.paste_through_gates(
                    self.app.state, info.session.id, envelope(message),
                    GateOptions(idle_only=True, expected_epoch=message['receiver_epoch'], expected_uuid=message['receiver_uuid']))
        except PasteRefused as refusal:
            await _refuse_delivery(row, message, refusal.code, refusal.nothing_landed)
            return
        except (OSError, RuntimeError, ToolError) as exc:
            logger.warning('crosstalk_delivery_failed', message_id=message['id'], error_type=type(exc).__name__)
            await asyncio.to_thread(store.finish, message['id'], 'failed', 'delivery uncertain; manual review required')
            return
        await asyncio.to_thread(store.finish, message['id'], 'delivered')


async def _refuse_delivery(row: Any, message: dict, code: str, nothing_landed: bool) -> None:
    if nothing_landed:
        await _discard_swarm(row)
    if code in ('paste_not_settled',):
        await asyncio.to_thread(store.finish, message['id'], 'failed', 'paste submission uncertain; manual review required')
    elif code == 'receiver_instance_changed':
        await asyncio.to_thread(store.finish, message['id'], 'failed', code)
    elif code in ('pane_dialog_open', 'pane_not_an_agent', 'session_gone'):
        await asyncio.to_thread(store.finish, message['id'], 'held', code)
    else:
        await asyncio.to_thread(store.finish, message['id'], 'failed', code)


async def _record_swarm(receiver_key: str, message: dict) -> Optional[int]:
    from src.core.swarm import delivery
    return await asyncio.to_thread(delivery.record_for_key, receiver_key, 'crosstalk', f"crosstalk:msg:{message['id']}")


async def _discard_swarm(row: Optional[int]) -> None:
    if row is not None:
        from src.core.swarm import delivery
        await asyncio.to_thread(delivery.discard, row)


def gate_ready_ids(changes: dict) -> list[str]:
    upserts = (changes.get('list') or {}).get('upsert', [])
    return [u['key'] for u in upserts if (u.get('fields') or {}).get('startup_gate') == 'ready']


def wake(app: Any, receiver_key: str) -> None:
    dispatcher = getattr(app.state, 'crosstalk_dispatcher', None)
    if dispatcher is not None:
        dispatcher.wake(receiver_key)
