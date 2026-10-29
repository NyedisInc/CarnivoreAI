
from __future__ import annotations

import asyncio
import math
import time
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api import peer_auth
from src.core.crosstalk import directory, peer_create, store
from src.core.crosstalk.delivery import dispatcher
from src.core.federation import peer_hosts, shadow_rows
from src.core.hosts.identity import remote_session_id
from src.core.mcp.protocol import BatchView
from src.core.mcp.common import ToolError
from src.core.crosstalk.spawn import SpawnRequest, _flags, _folder, _worktree

router = APIRouter(prefix="/crosstalk", tags=["crosstalk"])


class PeerDelivery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r"^m-[A-Za-z0-9_-]{8,100}$")
    thread: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$')
    text: str = Field(min_length=1, max_length=store.MAX_TEXT)
    in_reply_to: str | None = Field(default=None, max_length=100)
    expect_reply: bool = False
    expires_at: float
    sender_tmux: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,128}$')
    sender_uuid: str = Field(min_length=1, max_length=128)
    sender_epoch: int
    sender_name: str = Field(min_length=1, max_length=256)
    sender_provider: str = Field(min_length=1, max_length=64)
    sender_model: str | None = Field(default=None, max_length=128)
    receiver_tmux: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,128}$')
    receiver_key: str = Field(min_length=1, max_length=128)
    receiver_epoch: int
    resume_generation: int = Field(default=0, ge=0, lt=2**31)
    window_generation: int = Field(default=0, ge=0, lt=2**31)


class PeerControl(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sender_uuid: str = Field(min_length=1, max_length=128)
    sender_epoch: int
    receiver_tmux: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,128}$')
    receiver_key: str = Field(min_length=1, max_length=128)
    receiver_epoch: int
    resume_generation: int = Field(default=0, ge=0, lt=2**31)
    window_generation: int = Field(default=0, ge=0, lt=2**31)


def _refuse(code: str, status: int = 409) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


@router.post("/peer-deliver")
async def peer_deliver(body: PeerDelivery, request: Request,
                       principal: peer_auth.Principal = Depends(peer_auth.require_peer_sessions)) -> dict:
    """Import a peer-owned sender once, then let the local durable dispatcher deliver it."""
    if not principal.is_peer or principal.grant is None:
        raise _refuse('peer_token_required', 403)
    grant = principal.grant
    if any(':' in name or name.startswith('remote:') for name in (body.sender_tmux, body.receiver_tmux)):
        raise _refuse('not_local')
    if not math.isfinite(body.expires_at) or body.expires_at <= time.time():
        raise _refuse('message_expired')
    from src.core.session_one_shot_gate import MAX_BODY_BYTES
    if (not body.text.strip() or len(body.text.encode('utf-8')) + 1024 > MAX_BODY_BYTES
            or any((ord(c) < 32 and c not in '\n\t') or 127 <= ord(c) <= 159 for c in body.text)):
        raise _refuse('invalid_peer_message')
    if any(any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value) for value in
           (body.sender_name, body.sender_provider, body.sender_model or '', body.thread)):
        raise _refuse('invalid_peer_identity')
    with closing(peer_auth.open_db()) as conn:
        host = peer_hosts.get(conn, grant.peer_install_id)
        local_install_id = peer_auth.read_install_id(conn)
    if host is None:
        raise _refuse('peer_unpaired', 401)
    prior = await asyncio.to_thread(store.peer_receipt, grant.peer_install_id, body.id)
    if prior is not None and prior['status'] in ('delivering', 'delivered', 'failed', 'expired'):
        if (prior['sender_key'] != shadow_rows.shadow_uuid(grant.peer_install_id, body.sender_uuid)
                or prior['sender_id'] != remote_session_id(host.key, body.sender_tmux)
                or not local_install_id or shadow_rows.shadow_uuid(local_install_id, prior['receiver_key']) != body.receiver_key
                or prior['sender_epoch'] != body.sender_epoch
                or prior['receiver_epoch'] != body.receiver_epoch or prior['text'] != body.text
                or prior['thread'] != body.thread or prior['in_reply_to'] != body.in_reply_to
                or prior['sender_name'] != body.sender_name or prior['sender_provider'] != body.sender_provider
                or prior['sender_model'] != body.sender_model):
            raise _refuse('receipt_identity_changed')
        return {'id': prior['id'], 'status': prior['status'], 'reason': prior['reason']}
    view = BatchView(request.app.state.session_manager, request.app)
    infos = await view.list_session_infos()
    info = next((i for i in infos if i.tmux_session == body.receiver_tmux and i.host_key == 'local'), None)
    if info is None or info.session.tmux_created_epoch != body.receiver_epoch:
        raise _refuse('receiver_instance_changed')
    cards = await directory.list_cards(view, include_remote=False)
    card = next((c for c in cards if c['id'] == info.session.id), None)
    if card is None or not card.get('session_uuid'):
        raise _refuse('receiver_not_ready')
    if not local_install_id or shadow_rows.shadow_uuid(local_install_id, card['session_uuid']) != body.receiver_key:
        raise _refuse('receiver_instance_changed')
    sender = {'key': shadow_rows.shadow_uuid(grant.peer_install_id, body.sender_uuid),
              'id': remote_session_id(host.key, body.sender_tmux), 'uuid': body.sender_uuid,
              'epoch': body.sender_epoch, 'name': body.sender_name, 'provider': body.sender_provider,
              'model': body.sender_model}
    receiver = {'key': card['session_uuid'], 'id': card['id'], 'uuid': card['session_uuid'],
                'epoch': body.receiver_epoch, 'name': card['name'], 'provider': card['provider'],
                'model': card['model']}
    try:
        if body.resume_generation or body.window_generation:
            await asyncio.to_thread(store.apply_peer_control, sender['key'], receiver['key'],
                                    sender['epoch'], receiver['epoch'],
                                    resume_generation=body.resume_generation,
                                    window_generation=body.window_generation)
        received = await asyncio.to_thread(store.accept_peer, peer_install_id=grant.peer_install_id,
                                           message=body.model_dump(), sender=sender, receiver=receiver)
    except store.BusRefused as exc:
        raise HTTPException(status_code=409, detail={'code': 'crosstalk_refused', 'message': str(exc)}) from exc
    if received['status'] in ('queued', 'held'):
        dispatcher.wake(request.app, receiver['key'])
        active = getattr(request.app.state.crosstalk_dispatcher, '_tasks', {}).get(receiver['key']) if getattr(
            request.app.state, 'crosstalk_dispatcher', None) is not None else None
        if active is not None:
            try:
                await asyncio.wait_for(asyncio.shield(active), timeout=12)
            except asyncio.TimeoutError:
                pass
            received = await asyncio.to_thread(store.get, received['id']) or received
    return {'id': received['id'], 'status': received['status'], 'reason': received['reason']}


@router.post('/peer-control')
async def peer_control(body: PeerControl, request: Request,
                       principal: peer_auth.Principal = Depends(peer_auth.require_peer_sessions)) -> dict:
    if not principal.is_peer or principal.grant is None:
        raise _refuse('peer_token_required', 403)
    if not body.resume_generation and not body.window_generation:
        raise _refuse('empty_control')
    if ':' in body.receiver_tmux or body.receiver_tmux.startswith('remote:'):
        raise _refuse('not_local')
    with closing(peer_auth.open_db()) as conn:
        local_install_id = peer_auth.read_install_id(conn)
        host = peer_hosts.get(conn, principal.grant.peer_install_id)
    if not local_install_id or host is None:
        raise _refuse('peer_unpaired', 401)
    view = BatchView(request.app.state.session_manager, request.app)
    infos = await view.list_session_infos()
    info = next((i for i in infos if i.tmux_session == body.receiver_tmux and i.host_key == 'local'), None)
    if info is None or info.session.tmux_created_epoch != body.receiver_epoch:
        raise _refuse('receiver_instance_changed')
    cards = await directory.list_cards(view, include_remote=False)
    card = next((c for c in cards if c['id'] == info.session.id), None)
    if card is None or not card.get('session_uuid') or shadow_rows.shadow_uuid(local_install_id, card['session_uuid']) != body.receiver_key:
        raise _refuse('receiver_instance_changed')
    sender_key = shadow_rows.shadow_uuid(principal.grant.peer_install_id, body.sender_uuid)
    applied = await asyncio.to_thread(store.apply_peer_control, sender_key, card['session_uuid'],
                                      body.sender_epoch, body.receiver_epoch,
                                      resume_generation=body.resume_generation,
                                      window_generation=body.window_generation)
    return {'applied': applied}


class PeerSpawn(SpawnRequest):
    beast: bool = False


@router.post('/peer-spawn')
async def peer_spawn(body: PeerSpawn, request: Request,
                     principal: peer_auth.Principal = Depends(peer_auth.require_peer_sessions)) -> dict:
    """Create only here; the originating Mac owns the approval, caps, task and tab."""
    if not principal.is_peer or principal.grant is None:
        raise _refuse('peer_token_required', 403)
    if body.peer is not None or body.parent is not None:
        raise _refuse('not_local')
    if body.provider == 'claude' and body.effort in ('xhigh', 'max'):
        raise _refuse('invalid_effort')
    try:
        folder = await _folder(body, None)
        target_dir = await _worktree(folder, body.name or body.provider) if body.worktree else folder
    except (ValueError, ToolError) as exc:
        raise _refuse(str(exc)) from exc
    try:
        made = await peer_create.create_pane(request, target_dir=target_dir, agent_type=body.provider,
                                             label=body.name, model=body.model, extra_args=_flags(body, body.beast))
    except peer_create.PeerCreateRefused as exc:
        raise _refuse(exc.code, exc.status) from exc
    made.pop('row_id', None)
    return made
