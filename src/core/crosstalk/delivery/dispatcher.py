
from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace
from typing import Any, Optional

import structlog
from fastapi import HTTPException

from src.core import db
from src.core.crosstalk import store

logger = structlog.get_logger()


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
        self._last_status: dict[str, str] = {}
        self._startup_retries: dict[str, list[asyncio.TimerHandle]] = {}

    async def start(self) -> None:
        await asyncio.to_thread(store.recover_uncertain)
        self.schedule_expiry()
        asyncio.create_task(self._recover())

    async def _recover(self) -> None:
        from src.core.mcp.protocol import BatchView
        view = BatchView(self.app.state.session_manager, self.app)
        for info in await view.list_session_infos() + await view.list_peer_infos():
            if info.session.id.startswith('remote:peer-'):
                self.on_peer_change(info.session.id)
            else:
                self.on_status(info.session.id, info.activity_status)

    def close(self) -> None:
        if self._timer:
            self._timer.cancel()
        for handles in self._startup_retries.values():
            for handle in handles:
                handle.cancel()
        self._startup_retries.clear()
        for task in self._tasks.values():
            task.cancel()

    def _retry_native_startup(self, info: Any, message: dict) -> None:
        if (info.agent_family != 'codex' or message.get('source') not in ('crosstalk', 'peer')
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
        task.add_done_callback(self._task_error)

    async def _arm_expiry(self, generation: int) -> None:
        due = await asyncio.to_thread(store.next_expiry)
        if generation != self._expiry_generation:
            return
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if due is not None:
            self._timer = asyncio.get_running_loop().call_later(max(0, due - time.time()), self._on_expiry)

    def _on_expiry(self) -> None:
        task = asyncio.create_task(self._expire_and_schedule())
        task.add_done_callback(self._task_error)

    async def _expire_and_schedule(self) -> None:
        wake = await asyncio.to_thread(store.expire)
        for key in wake:
            self.wake(key)
        self.schedule_expiry()

    def on_status(self, session_id: str, status: str) -> None:
        notify_watch = status == 'idle' and self._last_status.get(session_id) != 'idle'
        self._last_status[session_id] = status
        if status not in ('idle', 'working', 'working_subagent', 'notice', 'finished_unread', 'unknown'):
            return
        task = asyncio.create_task(self._on_idle(session_id, notify_watch=notify_watch))
        task.add_done_callback(self._task_error)

    def on_peer_change(self, session_id: str | None = None) -> None:
        task = asyncio.create_task(self._on_peer_change(session_id))
        task.add_done_callback(self._task_error)

    async def _on_peer_change(self, session_id: str | None) -> None:
        from src.core.crosstalk import directory
        from src.core.mcp.protocol import BatchView
        cards = await directory.list_cards(BatchView(self.app.state.session_manager, self.app), include_remote=True)
        for card in cards:
            if card['id'].startswith('remote:peer-') and (session_id is None or card['id'] == session_id):
                self.wake(str(card.get('session_uuid') or card['id']))

    @staticmethod
    def _task_error(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.warning('crosstalk_dispatch_task_failed', error_type=type(task.exception()).__name__)

    async def _on_idle(self, session_id: str, *, notify_watch: bool) -> None:
        from src.core.crosstalk import directory
        from src.core.mcp.protocol import BatchView
        info = await self.app.state.session_manager.get_session_info(session_id=session_id)
        if info is None:
            return
        if info.activity_status == 'unknown':
            if (info.agent_family != 'codex' or info.startup_gate != 'ready'
                    or not info.claude_session_uuid):
                return
        elif info.activity_status not in ('idle', 'working', 'working_subagent', 'notice', 'finished_unread'):
            return
        cards = await directory.list_cards(BatchView(self.app.state.session_manager, self.app), include_remote=False)
        card = next((c for c in cards if c['id'] == info.session.id), None)
        if card is None:
            return
        key = card.get('session_uuid') or card['id']
        if info.activity_status == 'idle' and notify_watch:
            watch_keys = await asyncio.to_thread(store.notify_idle, str(key), info.session.tmux_created_epoch)
            for watch_key in watch_keys:
                self.wake(watch_key)
        self.wake(str(key))

    def wake(self, receiver_key: str) -> None:
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
        if info.activity_status == 'question' or info.startup_gate != 'ready':
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
        from src.core.session_one_shot_gate import PROMPT_READY_STATUSES
        if info.activity_status not in PROMPT_READY_STATUSES:
            await _discard_swarm(row)
            await asyncio.to_thread(store.finish, message['id'], 'held', 'waiting for a ready prompt')
            self._retry_native_startup(info, message)
            return
        from src.api.one_shot_routes import paste_through_gates
        from src.core.mcp.common import ToolError
        try:
            if federated.is_remote(info):
                await federated.forward(info, 'POST', '/sessions/{session_id}/skills/one-shot',
                                        {'text': envelope(message), 'idle_only': True})
            else:
                await paste_through_gates(SimpleNamespace(app=self.app), info.session.id, envelope(message),
                                          idle_only=True, expected_epoch=message['receiver_epoch'],
                                          expected_uuid=message['receiver_uuid'])
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            code = detail.get('code', 'paste_refused')
            from src.core.swarm import delivery as swarm_delivery
            if swarm_delivery.nothing_landed(exc):
                await _discard_swarm(row)
            if code in ('paste_not_settled',):
                await asyncio.to_thread(store.finish, message['id'], 'failed', 'paste submission uncertain; manual review required')
            elif code == 'receiver_instance_changed':
                await asyncio.to_thread(store.finish, message['id'], 'failed', code)
            elif code in ('pane_dialog_open', 'pane_not_an_agent', 'session_gone'):
                await asyncio.to_thread(store.finish, message['id'], 'held', code)
            else:
                await asyncio.to_thread(store.finish, message['id'], 'failed', code)
            return
        except (OSError, RuntimeError, ToolError) as exc:
            logger.warning('crosstalk_delivery_failed', message_id=message['id'], error_type=type(exc).__name__)
            await asyncio.to_thread(store.finish, message['id'], 'failed', 'delivery uncertain; manual review required')
            return
        await asyncio.to_thread(store.finish, message['id'], 'delivered')


async def _record_swarm(receiver_key: str, message: dict) -> Optional[int]:
    from src.core.swarm import delivery
    return await asyncio.to_thread(delivery.record_for_key, receiver_key, 'crosstalk', f"crosstalk:msg:{message['id']}")


async def _discard_swarm(row: Optional[int]) -> None:
    if row is not None:
        from src.core.swarm import delivery
        await asyncio.to_thread(delivery.discard, row)


def wake(app: Any, receiver_key: str) -> None:
    dispatcher = getattr(app.state, 'crosstalk_dispatcher', None)
    if dispatcher is not None:
        dispatcher.wake(receiver_key)
