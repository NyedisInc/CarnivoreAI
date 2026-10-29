
from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

import structlog

from src.core.crosstalk import directory, store
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError


def _identity(card: dict, epoch: int | None) -> dict:
    key = card.get('session_uuid') or card['id']
    return {'key': str(key), 'id': card['id'], 'uuid': card.get('session_uuid'),
            'epoch': epoch, 'name': card['name'], 'provider': card.get('provider') or 'agent',
            'model': card.get('model')}


logger = structlog.get_logger(__name__)

_AGENT_HANDLE = re.compile(r'^agent:([1-9][0-9]*)$')


WAKE_WAIT_S = 90.0

INBOX_LIMIT = 20
RECEIPT_WAIT_S = 3.0
_RECEIPTS = {'delivered': 'delivered', 'held': 'stuck', 'failed': 'stuck', 'expired': 'stuck'}
INBOX_MAX = 100


class WakePending(ToolError):

    def __init__(self, agent_id: int | None, wake: asyncio.Future | None = None) -> None:
        super().__init__('agent is waking; your message is queued and goes in once its body is up')
        self.agent_id = agent_id
        self.wake = wake


_slow_wake_tasks: set[asyncio.Task] = set()
SLOW_WAKE_QUEUE_S = 1800.0


async def _wake_agent(app_state: Any, agent_id: int) -> None:
    from src.core.swarm import body  # noqa: PLC0415

    if app_state is None:
        raise ToolError('agent is asleep and this caller cannot wake it')

    async def wake_and_wait() -> None:
        result = await body.wake(app_state, agent_id, 'crosstalk', 'data')
        if result.state != 'awake':
            await body.wait_awake(agent_id)

    task = asyncio.ensure_future(wake_and_wait())
    try:
        await asyncio.wait_for(asyncio.shield(task), WAKE_WAIT_S)
    except TimeoutError:
        raise WakePending(agent_id, task) from None
    except body.BodyError as exc:
        raise ToolError(str(exc)) from None


async def _wake_asleep_session(view: Any, uuid: str) -> None:
    from fastapi import HTTPException  # noqa: PLC0415

    from src.api.session_sleep_routes import wake_by_uuid  # noqa: PLC0415

    app = getattr(view, 'app', None)
    if app is None:
        raise ToolError('agent is asleep and this caller cannot wake it')
    try:
        async with asyncio.timeout(WAKE_WAIT_S):
            result = await wake_by_uuid(app.state, uuid)
    except TimeoutError:
        raise ToolError('agent is waking; your message was not sent') from None
    except HTTPException as exc:
        raise ToolError(f'could not wake the agent ({exc.detail}); your message was not sent') from None
    if result.status != 'started':
        raise ToolError(f'could not wake the agent: {result.detail}; your message was not sent')


async def _await_live(view: Any, caller: AgentCaller, uuid: str, timeout: float = WAKE_WAIT_S) -> tuple[dict, dict]:
    try:
        async with asyncio.timeout(timeout):
            while True:
                try:
                    return await identities(view.fresh(), caller, uuid, asleep='poll')
                except ToolError as exc:
                    if 'is asleep' not in str(exc) and 'no agent matches' not in str(exc):
                        raise
                await asyncio.sleep(0.5)
    except TimeoutError:
        raise WakePending(None) from None


async def _agent_handle(to: str, app_state: Any) -> str:
    match = _AGENT_HANDLE.match(to.strip()) if isinstance(to, str) else None
    if match is None:
        return to
    await _wake_agent(app_state, int(match.group(1)))
    uuid = await asyncio.to_thread(directory.agent_session_uuid, int(match.group(1)))
    if uuid is None:
        raise ToolError(f'agent {match.group(1)} has no live session; wake it first')
    return uuid


async def _sender(view: Any, caller: AgentCaller, cards: list[dict], infos: list | None = None) -> dict:
    if caller.external:
        return {'key': caller.current_session_id, 'id': caller.current_session_id,
                'uuid': None, 'epoch': None, 'name': caller.token_name,
                'provider': 'external', 'model': None}
    infos = infos if infos is not None else await view.list_session_infos() + await view.list_peer_infos()
    own = next((c for c in cards if c['is_you']), None)
    own_info = next((row for row in infos if row.tmux_session == caller.tmux_name
                     and row.session.id in (caller.current_session_id, caller.session_id)), None)
    if own is None or own_info is None:
        raise ToolError('your authenticated pane is no longer listed')
    return _identity(own, own_info.session.tmux_created_epoch)


def _asleep_epoch(uuid: str) -> int | None:
    from contextlib import closing
    from src.core.db import connect, db_path_for
    from src.config import settings
    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            row = conn.execute('SELECT tmux_created_epoch FROM sessions WHERE session_uuid=?', (uuid,)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return row['tmux_created_epoch'] if row else None


async def identities(view: Any, caller: AgentCaller, to: str, *, asleep: str = 'refuse') -> tuple[dict, dict]:
    if not isinstance(to, str) or not to.strip():
        raise ToolError('to is required: choose a handle or agent id from agents_lookup')
    to = await _agent_handle(to, view.app.state if getattr(view, 'app', None) is not None else None)
    cards = await directory.list_cards(view, self_tmux=None if caller.external else caller.tmux_name, include_asleep=True)
    result = await directory.resolve_handle_async(to, cards)
    if not result.matches:
        raise ToolError(f'no agent matches {to!r}')
    if result.ambiguous:
        raise ToolError('ambiguous agent; choose one id: ' + ', '.join(c['id'] for c in result.matches[:10]))
    if result.tier not in directory.EXACT_TIERS:
        raise ToolError(f'no agent is named {to!r}; closest: ' + ', '.join(c['name'] for c in result.matches[:5])
                        + '. Use agents_lookup and send to its id.')
    receiver_card = result.matches[0]
    if receiver_card.get('asleep'):
        if receiver_card.get('swarm_agent_id') is not None and asleep != 'poll':
            await _wake_agent(view.app.state if getattr(view, 'app', None) is not None else None, receiver_card['swarm_agent_id'])
            return await _await_live(view, caller, receiver_card['session_uuid'])
        if asleep != 'allow':
            raise ToolError(f"{receiver_card['name']} is asleep; crosstalk_send wakes it, other tools do not")
        sender = await _sender(view, caller, cards)
        return sender, {'key': receiver_card['session_uuid'], 'id': receiver_card['id'], 'uuid': receiver_card['session_uuid'],
                        'epoch': None, 'name': receiver_card['name'], 'provider': receiver_card.get('provider') or 'agent',
                        'model': receiver_card.get('model'), 'asleep': True}
    infos = await view.list_session_infos() + await view.list_peer_infos()
    info = next((row for row in infos if row.session.id == receiver_card['id']), None)
    if info is None:
        raise ToolError('the target disappeared; look it up again')
    receiver = _identity(receiver_card, info.session.tmux_created_epoch)
    sender = await _sender(view, caller, cards, infos)
    if sender['key'] == receiver['key']:
        raise ToolError('crosstalk needs another agent as its target')
    return sender, receiver


async def caller_identity(view: Any, caller: AgentCaller) -> dict:
    if caller.external:
        return {'key': caller.current_session_id, 'id': caller.current_session_id,
                'uuid': None, 'epoch': None, 'name': caller.token_name, 'provider': 'external'}
    cards = await directory.list_cards(view, self_tmux=caller.tmux_name, include_remote=False)
    own = next((c for c in cards if c['is_you']), None)
    infos = await view.list_session_infos()
    info = next((row for row in infos if row.tmux_session == caller.tmux_name
                 and row.session.id in (caller.current_session_id, caller.session_id)), None)
    if own is None or info is None:
        raise ToolError('your authenticated pane is no longer listed')
    return _identity(own, info.session.tmux_created_epoch)


def receipt_of(status: str) -> str:
    return _RECEIPTS.get(status, 'queued')


async def settle(message_id: str, timeout: float = RECEIPT_WAIT_S) -> tuple:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        generation = store.version()
        row = await asyncio.to_thread(store.get, message_id)
        status = row['status'] if row else 'failed'
        remaining = deadline - loop.time()
        if receipt_of(status) != 'queued' or remaining <= 0 or not await store.changed(remaining, generation):
            return status, (row or {}).get('reason')


def _check_message(text: Any, expect_reply: Any) -> None:
    if not isinstance(text, str) or not text.strip() or len(text) > store.MAX_TEXT:
        raise ToolError(f'text must contain 1 to {store.MAX_TEXT} characters')
    from src.core.session_one_shot_gate import MAX_BODY_BYTES
    try:
        raw = text.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ToolError('text is not valid UTF-8') from exc
    if len(raw) + 1024 > MAX_BODY_BYTES:
        raise ToolError('message plus crosstalk header exceeds the guarded paste size limit')
    if any((ord(c) < 32 and c not in '\n\t') or 127 <= ord(c) <= 159 for c in text):
        raise ToolError('message contains control characters that the paste guard would alter')
    if not isinstance(expect_reply, bool):
        raise ToolError('expect_reply must be true or false')


async def send(view: Any, caller: AgentCaller, *, to: str, text: str,
               thread: str | None = None, in_reply_to: str | None = None,
               expect_reply: bool = False, action: str = 'crosstalk_send',
               owner_approved: bool = False, source: str = 'crosstalk', task_item: int | None = None) -> dict:
    from src.core.mcp import beast_mode, write_tools
    _check_message(text, expect_reply)
    try:
        sender, receiver = await identities(view, caller, to, asleep='allow')
    except WakePending as slow:
        return _queue_slow_wake(view, caller, slow, dict(
            to=to, text=text, thread=thread, in_reply_to=in_reply_to, expect_reply=expect_reply, action=action,
            owner_approved=owner_approved, source=source, task_item=task_item))
    if in_reply_to:
        parent = await asyncio.to_thread(store.get, in_reply_to)
        if parent is None or parent['receiver_key'] != sender['key'] or parent['sender_key'] != receiver['key']:
            raise ToolError('reply target is not a message sent to you by this agent')
    async def perform(approved: bool) -> dict:
        if receiver.get('asleep'):
            await _wake_asleep_session(view, receiver['uuid'])
            fresh_sender, fresh_receiver = await _await_live(view, caller, receiver['uuid'])
            if (fresh_sender['key'], fresh_sender['epoch'], fresh_receiver['key']) != (sender['key'], sender['epoch'], receiver['key']):
                raise ToolError('a participant is now a different pane; nothing was sent')
        else:
            fresh_sender, fresh_receiver = await identities(view.fresh(), caller, receiver['id'])
            if (fresh_sender['key'], fresh_sender['epoch'], fresh_receiver['key'], fresh_receiver['epoch']) != (
                    sender['key'], sender['epoch'], receiver['key'], receiver['epoch']):
                raise ToolError('a participant is now a different pane; nothing was sent')
        if approved:
            await asyncio.to_thread(store.grant_contact, fresh_sender['key'], fresh_receiver['key'],
                                    fresh_sender['epoch'], fresh_receiver['epoch'])
        try:
            message = await asyncio.to_thread(store.reserve, sender=fresh_sender, receiver=fresh_receiver, text=text,
                                               thread=thread, in_reply_to=in_reply_to, expect_reply=expect_reply, source=source,
                                               spawn_task=action == 'agent_spawn', task_item=task_item)
        except store.BusRefused as exc:
            if 'loop breaker' in str(exc):
                return await _resume_loop(view, caller, fresh_sender, fresh_receiver, text, thread, in_reply_to, expect_reply, source, task_item)
            raise ToolError(str(exc)) from exc
        from src.core.crosstalk.delivery import dispatcher
        dispatcher.wake(view.app, fresh_receiver['key'])
        status, reason = await settle(message['id'])
        return {'id': message['id'], 'thread': message['thread'], 'status': status, 'receipt': receipt_of(status),
                'reason': reason, 'to': fresh_receiver['id'], 'expires_at': message['expires_at']}
    pinned_epoch = receiver['epoch']
    if receiver.get('asleep'):
        pinned_epoch = await asyncio.to_thread(_asleep_epoch, receiver['uuid'])
    if await asyncio.to_thread(store.contact, sender['key'], receiver['key'], sender['epoch'], pinned_epoch):
        return await perform(False)
    if owner_approved:
        return await perform(True)
    if beast_mode.approval_skip('crosstalk_send'):
        return await beast_mode.run_unprompted(caller, 'crosstalk_send', lambda: perform(True),
            target_id=receiver['id'], target_tmux=receiver['name'], summary='first contact: send crosstalk message',
            args={'to': receiver['id'], 'text': text})
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    async def approved_result(approved: bool) -> dict:
        from src.core.mcp.common import _ok
        result = await perform(approved)
        return result if 'content' in result else _ok(result)
    return await write_tools.park(view, caller, receiver['id'], receiver['name'], 'crosstalk_send',
        'first contact: send crosstalk message', {'to': receiver['id'], 'text': text}, approved_result, digest)


def _queue_slow_wake(view: Any, caller: AgentCaller, slow: WakePending, kwargs: dict) -> dict:
    async def finish() -> None:
        from src.core.swarm import body  # noqa: PLC0415
        try:
            async with asyncio.timeout(SLOW_WAKE_QUEUE_S):
                if slow.wake is not None:
                    await asyncio.shield(slow.wake)
                if slow.agent_id is not None:
                    await body.wait_awake(slow.agent_id)
            await send(view.fresh(), caller, **kwargs)
        except (ToolError, body.BodyError, TimeoutError) as exc:
            logger.warning('crosstalk_slow_wake_send_failed', agent_id=slow.agent_id, error=str(exc)[:300])

    task = asyncio.get_running_loop().create_task(finish())
    _slow_wake_tasks.add(task)
    task.add_done_callback(_slow_wake_tasks.discard)
    return {'status': 'queued', 'receipt': 'queued', 'to': kwargs['to'], 'reason': str(slow)}


async def _resume_loop(view: Any, caller: AgentCaller, sender: dict, receiver: dict, text: str,
                       thread: str | None, in_reply_to: str | None, expect_reply: bool, source: str = 'crosstalk',
                       task_item: int | None = None) -> dict:
    from src.core.mcp import write_tools
    async def run(approved: bool) -> dict:
        fresh_sender, fresh_receiver = await identities(view.fresh(), caller, receiver['id'])
        if (fresh_sender['key'], fresh_sender['epoch'], fresh_receiver['key'], fresh_receiver['epoch']) != (
                sender['key'], sender['epoch'], receiver['key'], receiver['epoch']):
            raise ToolError('a participant is now a different pane; nothing was sent')
        await asyncio.to_thread(store.resume_pair, sender['key'], receiver['key'])
        from src.core.mcp.common import _ok
        result = await send(view.fresh(), caller, to=receiver['id'], text=text, thread=thread,
                            in_reply_to=in_reply_to, expect_reply=expect_reply, source=source, task_item=task_item)
        return result if 'content' in result else _ok(result)
    return await write_tools.park(view, caller, receiver['id'], receiver['name'], 'crosstalk_resume',
        'resume a conversation paused after 30 messages without owner input',
        {'to': receiver['id'], 'text': text}, run, hashlib.sha256(text.encode('utf-8')).hexdigest())


async def reply(view: Any, caller: AgentCaller, *, message_id: str, text: str, task_item: int | None = None) -> dict:
    sender = await caller_identity(view, caller)
    parent = await asyncio.to_thread(store.get, message_id)
    if parent is None or parent['receiver_key'] != sender['key'] or parent['receiver_epoch'] != sender['epoch']:
        raise ToolError('no such message addressed to your current pane')
    if parent['source'] == 'system':
        raise ToolError('status notices cannot be replied to')
    if parent['sender_key'].startswith('mcp-token:') or parent['sender_key'] == 'owner':
        receiver = {'key': parent['sender_key'], 'id': parent['sender_id'],
                    'uuid': None, 'epoch': None, 'name': parent['sender_name'],
                    'provider': 'external', 'model': None}
        try:
            message = await asyncio.to_thread(store.reserve, sender=sender, receiver=receiver, text=text,
                                              thread=parent['thread'], in_reply_to=message_id, task_item=task_item)
        except store.BusRefused as exc:
            raise ToolError(str(exc)) from exc
        await asyncio.to_thread(store.deliver_external, message['id'])
        return {'id': message['id'], 'thread': message['thread'], 'status': 'delivered',
                'to': receiver['id']}
    return await send(view, caller, to=parent['sender_key'], text=text,
                      thread=parent['thread'], in_reply_to=message_id, action='crosstalk_reply', task_item=task_item)


async def inbox(view: Any, caller: AgentCaller, *, since: float = 0,
                thread: str | None = None, limit: int = INBOX_LIMIT) -> dict:
    identity = await caller_identity(view, caller)
    messages, watches = await asyncio.gather(
        asyncio.to_thread(store.messages_for, identity['key'], since=since, thread=thread, limit=limit, newest_first=True),
        asyncio.to_thread(store.watches_for, identity['key']))
    return {'messages': messages, 'watches': watches}


def grant_contact(sender_key: str, receiver_key: str, sender_epoch: int | None,
                  receiver_epoch: int | None, *, source: str = 'spawn') -> None:
    store.grant_contact(sender_key, receiver_key, sender_epoch, receiver_epoch, source=source)
