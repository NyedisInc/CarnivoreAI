
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.agent_spawn_routes import spawn_for_caller
from src.core.crosstalk import spawn, spawn_remote
from src.core.federation import peer_listing, shadow_rows
from src.core.mcp import federated
from src.core.mcp.caller import AgentCaller

PEER = SimpleNamespace(peer_install_id='peer-install', key='peer-x', label='far')
CREATED = {'session_uuid': 'far-uuid', 'epoch': 5, 'tmux_name': 'carnivore_mac-2'}


def row(uuid_: str = 'far-uuid') -> SimpleNamespace:
    return SimpleNamespace(session=SimpleNamespace(id='remote:peer-x:carnivore_mac-2', tmux_created_epoch=5),
                           session_uuid=shadow_rows.shadow_uuid('peer-install', uuid_))


def patch_listing(monkeypatch, looks_before_row: int, rows: list) -> list:
    looks: list = []

    async def refresh(*_a, **_k):
        looks.append(1)

    async def infos(**_k):
        return rows if len(looks) > looks_before_row else []

    monkeypatch.setattr(peer_listing, 'refresh', refresh)
    monkeypatch.setattr(federated, 'peer_infos', infos)
    return looks


@pytest.mark.asyncio
async def test_confirm_waits_for_late_listing_and_never_accepts_a_wrong_identity(monkeypatch) -> None:
    pick = lambda i: i.session.id == 'remote:peer-x:carnivore_mac-2'  # noqa: E731
    looks = patch_listing(monkeypatch, 2, [row()])
    found = await spawn_remote.confirm_created_child(PEER, CREATED, pick, timeout=5, interval=0.01)
    assert found is not None and len(looks) == 3

    patch_listing(monkeypatch, 0, [row('replacement-uuid')])
    assert await spawn_remote.confirm_created_child(PEER, CREATED, pick, timeout=0.05, interval=0.01) is None

    async def refused(*_a, **_k):
        raise spawn_remote.CreatedUnconfirmed('remote:peer-x:carnivore_mac-2', 'raw text with /Users/demo/secret/path')

    monkeypatch.setattr(spawn, 'spawn', refused)
    view = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=None)))
    with pytest.raises(Exception) as err:
        await spawn_for_caller(SimpleNamespace(app=view.app), spawn.SpawnRequest(provider='codex', task='t', working_dir='/w'),
                               AgentCaller('ses_p', 'cloude_p', 'ses_p'))
    detail = err.value.detail
    assert detail['created_session'] == 'remote:peer-x:carnivore_mac-2' and detail['code'] == 'spawn_created_unconfirmed'
    assert 'secret' not in str(detail)
