
from __future__ import annotations

import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault('DEFAULT_WORKING_DIR', tempfile.mkdtemp(prefix='cc_peer_wd_'))
os.environ.setdefault('LOG_DIRECTORY', tempfile.mkdtemp(prefix='cc_peer_logs_'))
os.environ.setdefault('TOTP_SECRET', 'testsecretnotreal')
os.environ.setdefault('JWT_SECRET', 'testjwtnotreal')

from fastapi.testclient import TestClient

from src.api import peer_auth
from src.api.auth import require_auth
from src.config import settings
from src.core.crosstalk import directory, store
from src.core.db import connect, db_path_for, get_meta
from src.core.db_migration import ensure_db_migrated
from src.core.federation import fed_key, grants, peer_hosts, peer_token, shadow_rows
from src.core.hosts.identity import remote_session_id
from src.main import app
from src.models import Session, SessionInfo


def test_live_peer_grant_and_pinned_receipt(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    def opened():
        return connect(path, create=False)
    monkeypatch.setattr(peer_auth, 'open_db', opened)
    monkeypatch.setattr(store, '_conn', opened)
    monkeypatch.setattr(store, '_notify', lambda: None)
    monkeypatch.setattr(type(settings), 'get_state_dir', lambda self: tmp_path)
    with closing(opened()) as conn:
        local_id = get_meta(conn, 'install_id')
        key = fed_key.DeviceKey.from_seed(bytes([7]) * 32)
        grant = grants.create_grant(conn, peer_install_id='peer-install', public_key=fed_key.public_key_b64(key), label='hosta')
        peer_hosts.upsert(conn, install_id='peer-install', label='hosta', grant_id=grant.grant_id,
                          fid=grant.fid, initiator=False)
    token, _ = peer_token.mint(grant, local_id)
    info = SessionInfo(session=Session(id='ses_local', working_dir='/tmp', agent_type='claude',
                                       tmux_created_epoch=42), tmux_session='cloude_local',
                       session_row_id=1, host_key='local', label='Receiver', activity_status='idle',
                       agent_family='claude')
    class Manager:
        async def list_session_infos(self):
            return [info]
    monkeypatch.setattr(app.state, 'session_manager', Manager(), raising=False)
    monkeypatch.setattr(app.state, 'crosstalk_dispatcher', None, raising=False)
    monkeypatch.setattr(directory, '_session_details', lambda _ids: {1: ('uuid-local', None, [])})
    body = {'id': 'm-peerorigin001', 'thread': 't-one', 'text': 'hello', 'expires_at': 9999999999,
            'sender_tmux': 'cloude_sender', 'sender_uuid': 'uuid-sender', 'sender_epoch': 11,
            'sender_name': 'Sender', 'sender_provider': 'codex', 'receiver_tmux': 'cloude_local',
            'receiver_key': shadow_rows.shadow_uuid(local_id, 'uuid-local'), 'receiver_epoch': 42}
    client = TestClient(app, raise_server_exceptions=False)
    route = '/api/v1/crosstalk/peer-deliver'
    assert client.post(route, json=body).status_code == 401
    app.dependency_overrides[require_auth] = lambda: None
    try:
        assert client.post(route, json=body).status_code == 403
    finally:
        app.dependency_overrides.pop(require_auth, None)
    headers = {'Authorization': f'Bearer {token}'}
    first = client.post(route, json=body, headers=headers)
    assert first.status_code == 200, first.text
    again = client.post(route, json=body, headers=headers)
    assert again.status_code == 200 and again.json()['id'] == first.json()['id']
    assert len(store.messages_for('uuid-local')) == 1
    remote_key = shadow_rows.shadow_uuid('peer-install', body['sender_uuid'])
    assert store.contact('uuid-local', remote_key, 42, 11)
    assert store.peer_reply_origin_id(first.json()['id'], 'peer-install', sender_key='uuid-local',
                                      receiver_key=remote_key, thread='t-one') == body['id']
    reply = store.reserve(sender={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                                  'name': 'Receiver', 'provider': 'claude', 'model': None},
                          receiver={'key': remote_key, 'id': 'remote:peer-x:cloude_sender',
                                    'uuid': remote_key, 'epoch': 11, 'name': 'Sender',
                                    'provider': 'codex', 'model': None},
                          text='reply', thread='t-one', in_reply_to=first.json()['id'])
    assert reply['in_reply_to'] == first.json()['id']
    returned = store.accept_peer(peer_install_id='peer-install',
        message={'id': 'm-peerorigin004', 'thread': 't-one', 'text': 'answer',
                 'in_reply_to': reply['id'], 'expires_at': 9999999999},
        sender={'key': remote_key, 'id': remote_session_id(peer_hosts.host_key_for('peer-install'), body['sender_tmux']),
                'uuid': body['sender_uuid'], 'epoch': 11,
                'name': 'Sender', 'provider': 'codex', 'model': None},
        receiver={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                  'name': 'Receiver', 'provider': 'claude', 'model': None})
    assert returned['in_reply_to'] == reply['id']
    with closing(opened()) as conn:
        conn.execute('UPDATE crosstalk_contacts SET paused=1 WHERE pair_key=?',
                     (store.pair_key('uuid-local', remote_key),))
    with pytest.raises(store.BusRefused, match='loop breaker'):
        store.accept_peer(peer_install_id='peer-install',
            message={'id': 'm-peerorigin005', 'thread': 't-one', 'text': 'without origin resume',
                     'expires_at': 9999999999},
            sender={'key': remote_key, 'id': remote_session_id(peer_hosts.host_key_for('peer-install'), body['sender_tmux']),
                    'uuid': body['sender_uuid'], 'epoch': 11, 'name': 'Sender', 'provider': 'codex', 'model': None},
            receiver={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                      'name': 'Receiver', 'provider': 'claude', 'model': None})
    with pytest.raises(store.BusRefused, match='paused'):
        store.reserve(sender={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                              'name': 'Receiver', 'provider': 'claude', 'model': None},
                      receiver={'key': remote_key, 'id': 'remote:peer-x:cloude_sender',
                                'uuid': remote_key, 'epoch': 11, 'name': 'Sender',
                                'provider': 'codex', 'model': None}, text='local send still paused')
    control = {'sender_uuid': body['sender_uuid'], 'sender_epoch': 11,
               'receiver_tmux': body['receiver_tmux'], 'receiver_key': body['receiver_key'],
               'receiver_epoch': 42}
    control_route = '/api/v1/crosstalk/peer-control'
    assert client.post(control_route, json={**control, 'window_generation': 1}).status_code == 401
    window = client.post(control_route, json={**control, 'window_generation': 1}, headers=headers)
    assert window.status_code == 200 and window.json()['applied']
    with pytest.raises(store.BusRefused, match='paused'):
        store.reserve(sender={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                              'name': 'Receiver', 'provider': 'claude', 'model': None},
                      receiver={'key': remote_key, 'id': 'remote:peer-x:cloude_sender',
                                'uuid': remote_key, 'epoch': 11, 'name': 'Sender',
                                'provider': 'codex', 'model': None}, text='window alone cannot resume')
    resume = client.post(control_route, json={**control, 'resume_generation': 1}, headers=headers)
    assert resume.status_code == 200 and resume.json()['applied']
    replay = client.post(control_route, json={**control, 'resume_generation': 1}, headers=headers)
    assert replay.status_code == 200 and not replay.json()['applied']
    resumed = store.reserve(sender={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                                    'name': 'Receiver', 'provider': 'claude', 'model': None},
                            receiver={'key': remote_key, 'id': 'remote:peer-x:cloude_sender',
                                      'uuid': remote_key, 'epoch': 11, 'name': 'Sender',
                                      'provider': 'codex', 'model': None}, text='reply after one remote resume')
    assert resumed['status'] == 'queued'
    with closing(opened()) as conn:
        conn.execute('UPDATE crosstalk_contacts SET paused=1 WHERE pair_key=?',
                     (store.pair_key('uuid-local', remote_key),))
    carried = client.post(route, json={**body, 'id': 'm-peerorigin006', 'text': 'next after resume',
                                       'resume_generation': 2}, headers=headers)
    assert carried.status_code == 200, carried.text
    assert store.contact('uuid-local', remote_key, 42, 11)
    assert store.peer_control_markers('uuid-local', remote_key, 42, 11) == (0, 0)
    assert store.reserve(sender={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                                 'name': 'Receiver', 'provider': 'claude', 'model': None},
                         receiver={'key': remote_key, 'id': 'remote:peer-x:cloude_sender',
                                   'uuid': remote_key, 'epoch': 11, 'name': 'Sender',
                                   'provider': 'codex', 'model': None}, text='reply after carried resume')['status'] == 'queued'
    with closing(opened()) as conn:
        window = conn.execute('SELECT last_owner_input FROM crosstalk_contacts WHERE pair_key=?',
                              (store.pair_key('uuid-local', remote_key),)).fetchone()[0]
        total = conn.execute('''SELECT COUNT(*) FROM crosstalk_messages WHERE created_at>=? AND (
            (sender_key=? AND receiver_key=?) OR (sender_key=? AND receiver_key=?))''',
            (window, remote_key, 'uuid-local', 'uuid-local', remote_key)).fetchone()[0]
    for number in range(30 - total):
        store.accept_peer(peer_install_id='peer-install',
            message={'id': f'm-fill-{number:03d}', 'thread': 't-one', 'text': f'fill {number}',
                     'expires_at': 9999999999},
            sender={'key': remote_key, 'id': remote_session_id(peer_hosts.host_key_for('peer-install'),
                                                               body['sender_tmux']),
                    'uuid': body['sender_uuid'], 'epoch': 11, 'name': 'Sender',
                    'provider': 'codex', 'model': None},
            receiver={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                      'name': 'Receiver', 'provider': 'claude', 'model': None})
    capped = client.post(route, json={**body, 'id': 'm-peerorigin700', 'text': 'over loop cap'}, headers=headers)
    assert capped.status_code == 409 and 'loop breaker' in capped.text
    with closing(opened()) as conn:
        paused = conn.execute('SELECT paused FROM crosstalk_contacts WHERE pair_key=?',
                              (store.pair_key('uuid-local', remote_key),)).fetchone()[0]
    assert paused == 1
    assert client.post(route, json={**body, 'id': 'm-peerorigin701', 'text': 'after fresh resume',
                                    'resume_generation': 3}, headers=headers).status_code == 200
    assert client.post(control_route, json={**control, 'receiver_epoch': 43, 'window_generation': 2},
                       headers=headers).status_code == 409
    assert client.post(route, json={**body, 'text': 'changed'}, headers=headers).status_code == 409
    claimed = store.claim_for('uuid-local')
    assert claimed['id'] == first.json()['id']
    store.finish(claimed['id'], 'delivered')
    prior = store.peer_receipt('peer-install', body['id'])
    assert prior is not None
    assert prior['sender_key'] == shadow_rows.shadow_uuid('peer-install', body['sender_uuid'])
    assert prior['sender_id'] == remote_session_id(peer_hosts.host_key_for('peer-install'), body['sender_tmux'])
    assert shadow_rows.shadow_uuid(local_id, prior['receiver_key']) == body['receiver_key']
    assert prior['sender_epoch'] == body['sender_epoch']
    assert prior['receiver_epoch'] == body['receiver_epoch']
    assert prior['text'] == body['text']
    info.session.tmux_created_epoch = 43
    retry = client.post(route, json=body, headers=headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()['status'] == 'delivered'
    assert client.post(route, json={**body, 'id': 'm-peerorigin002'}, headers=headers).status_code == 409
    with closing(opened()) as conn:
        grants.revoke(conn, grant.grant_id)
    assert client.post(route, json={**body, 'id': 'm-peerorigin003'}, headers=headers).status_code == 401
    with closing(opened()) as conn:
        conn.execute('UPDATE crosstalk_contacts SET paused=1 WHERE pair_key=?',
                     (store.pair_key('uuid-local', remote_key),))
    replaced = store.accept_peer(peer_install_id='peer-install',
        message={'id': 'm-new-epoch', 'thread': 't-new', 'text': 'fresh pane', 'expires_at': 9999999999},
        sender={'key': remote_key, 'id': remote_session_id(peer_hosts.host_key_for('peer-install'),
                                                           body['sender_tmux']),
                'uuid': body['sender_uuid'], 'epoch': 12, 'name': 'Sender',
                'provider': 'codex', 'model': None},
        receiver={'key': 'uuid-local', 'id': 'ses_local', 'uuid': 'uuid-local', 'epoch': 42,
                  'name': 'Receiver', 'provider': 'claude', 'model': None})
    assert replaced['status'] == 'queued'
    with closing(opened()) as conn:
        fresh = conn.execute('SELECT paused,source FROM crosstalk_contacts WHERE pair_key=?',
                             (store.pair_key('uuid-local', remote_key),)).fetchone()
    assert fresh['paused'] == 0 and fresh['source'] == 'peer'
