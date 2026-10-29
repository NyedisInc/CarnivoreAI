
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any

from src.api import peer_auth
from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.hosts.identity import parse_remote_session_id


async def propagate_owner_window(app: Any, card: dict, updates: list[tuple[str, int | None, int | None, int]]) -> None:
    if not card.get('session_uuid') or not updates:
        return
    from src.core.mcp.protocol import BatchView
    view = BatchView(app.state.session_manager, app)
    infos = await view.list_peer_infos()
    with closing(peer_auth.open_db()) as conn:
        peers = {p.key: p for p in peer_hosts.list_peers(conn)}
    links = peer_links.LINKS
    if links is None:
        return
    requests = []
    for remote_key, sender_epoch, receiver_epoch, generation in updates:
        info = next((i for i in infos if i.session_uuid == remote_key
                     and i.session.tmux_created_epoch == receiver_epoch and i.host_state == 'up'), None)
        parsed = parse_remote_session_id(info.session.id) if info is not None else None
        if parsed is None or parsed[0] not in peers:
            continue
        client = links.client(peers[parsed[0]].peer_install_id)
        if client is None:
            continue
        body = {'sender_uuid': card['session_uuid'], 'sender_epoch': sender_epoch,
                'receiver_tmux': parsed[1], 'receiver_key': remote_key, 'receiver_epoch': receiver_epoch,
                'window_generation': generation}
        requests.append(client.request('POST', '/api/v1/crosstalk/peer-control', json=body, timeout=8))
    if requests:
        await asyncio.gather(*requests, return_exceptions=True)


async def deliver(app: Any, info: Any, message: dict) -> tuple[str, str | None]:
    parsed = parse_remote_session_id(info.session.id)
    if parsed is None or not parsed[0].startswith('peer-'):
        return 'failed', 'target is not a paired-computer session'
    host_key, receiver_tmux = parsed
    if info.host_state != 'up':
        return 'held', 'paired computer is disconnected'
    with closing(peer_auth.open_db()) as conn:
        peer = next((p for p in peer_hosts.list_peers(conn) if p.key == host_key), None)
    if peer is None:
        return 'failed', 'paired computer is no longer paired'
    links = peer_links.LINKS
    client = links.client(peer.peer_install_id) if links is not None else None
    if client is None:
        return 'held', 'paired computer is disconnected'
    sender_info = await app.state.session_manager.get_session_info(session_id=message['sender_id'])
    if (sender_info is None or sender_info.host_key != 'local'
            or sender_info.session.tmux_created_epoch != message['sender_epoch']
            or not sender_info.tmux_session or not message['sender_uuid']):
        return 'failed', 'sender is a different pane instance'
    from src.core.crosstalk.directory import _session_details
    row_id = sender_info.session_row_id
    details = await asyncio.to_thread(_session_details, [row_id] if row_id is not None else [])
    if row_id is None or details.get(row_id, (None,))[0] != message['sender_uuid']:
        return 'failed', 'sender is a different durable session'
    body = {key: message[key] for key in ('id', 'thread', 'text', 'in_reply_to', 'expect_reply', 'expires_at',
                                           'sender_name', 'sender_provider', 'sender_model')}
    if message.get('in_reply_to'):
        from src.core.crosstalk import store
        origin_id = await asyncio.to_thread(store.peer_reply_origin_id, message['in_reply_to'],
                                            peer.peer_install_id, sender_key=message['sender_key'],
                                            receiver_key=message['receiver_key'], thread=message['thread'])
        if origin_id is None:
            return 'failed', 'reply target no longer matches the paired computer receipt'
        body['in_reply_to'] = origin_id
    body.update(sender_tmux=sender_info.tmux_session, sender_uuid=message['sender_uuid'],
                sender_epoch=message['sender_epoch'], receiver_tmux=receiver_tmux,
                receiver_key=message['receiver_key'], receiver_epoch=message['receiver_epoch'])
    from src.core.crosstalk import store
    resume, window = await asyncio.to_thread(store.peer_control_markers, message['sender_key'],
                                              message['receiver_key'], message['sender_epoch'],
                                              message['receiver_epoch'])
    body.update(resume_generation=resume, window_generation=window)
    try:
        reply = await client.request('POST', '/api/v1/crosstalk/peer-deliver', json=body, timeout=18)
    except (PeerUnreachable, PeerRefused, OSError):
        return 'held', 'paired computer did not confirm receipt'
    if reply.status_code == 200:
        try:
            result = reply.json()
        except (ValueError, TypeError):
            return 'held', 'paired computer receipt could not be read'
        status = result.get('status')
        if status == 'delivered':
            return 'delivered', None
        if status == 'failed':
            return 'failed', str(result.get('reason') or 'paired computer delivery failed')[:200]
        if status == 'expired':
            return 'held', 'paired computer receipt expired; local expiry will notify sender'
        if status in ('queued', 'held', 'delivering'):
            return 'held', 'waiting for paired computer delivery'
    if reply.status_code == 409:
        try:
            code = ((reply.json().get('detail') or {}).get('code'))
        except (ValueError, TypeError, AttributeError):
            code = None
        if code == 'receiver_not_ready':
            return 'held', 'paired computer agent is still starting'
    if reply.status_code in (409, 404):
        return 'failed', f'paired computer refused delivery ({reply.status_code})'
    return 'held', f'paired computer did not confirm receipt ({reply.status_code})'
