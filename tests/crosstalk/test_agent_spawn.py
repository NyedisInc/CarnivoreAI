
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.crosstalk import spawn, spawn_layout, spawn_remote
from src.core.federation import shadow_rows
from src.core.mcp.caller import AgentCaller


def info(session_id: str, row: int, name: str, epoch: int) -> SimpleNamespace:
    return SimpleNamespace(session=SimpleNamespace(id=session_id, tmux_created_epoch=epoch),
                           session_row_id=row, tmux_session=name, startup_gate='ready')


def test_spawn_layout_appends_without_replacing_existing_tabs() -> None:
    parent = info('ses_parent', 7, 'cloude_parent', 101)
    child = info('ses_child', 8, 'cloude_child', 102)
    arrangement = {'v': 1, 'sessions': {
        'cloude_other:50': {'layout': None, 'groups': {}},
        'cloude_parent:101': {'layout': None,
                              'groups': {'terminal:@primary': {'tabs': ['terminal:@primary', 'terminal:row:9']}}},
    }}
    changed = spawn_layout.add_to_arrangement(arrangement, parent, child)
    assert changed['sessions']['cloude_other:50'] == arrangement['sessions']['cloude_other:50']
    assert changed['sessions']['cloude_parent:101']['groups']['terminal:@primary']['tabs'] == [
        'terminal:@primary', 'terminal:row:9', 'terminal:row:8']
    assert arrangement['sessions']['cloude_parent:101']['groups']['terminal:@primary']['tabs'] == [
        'terminal:@primary', 'terminal:row:9']


def test_remote_spawn_requires_created_durable_uuid_even_when_name_and_epoch_match() -> None:
    created = {'session_uuid': 'durable-first', 'epoch': 102}
    child = SimpleNamespace(session=SimpleNamespace(tmux_created_epoch=102),
                            session_uuid=shadow_rows.shadow_uuid('peer-install', 'durable-first'))
    assert spawn_remote.same_created_child(child, created, 'peer-install')
    child.session_uuid = shadow_rows.shadow_uuid('peer-install', 'durable-replacement')
    assert not spawn_remote.same_created_child(child, created, 'peer-install')


@pytest.mark.asyncio
async def test_approved_spawn_creates_one_pane_then_sends_task(monkeypatch, tmp_path) -> None:
    from src.api import session_crud_routes
    from src.core.crosstalk import bus, directory, store
    from src.core.mcp import beast_mode, write_tools
    from src.core import session_change_notice

    parent = info('ses_parent', 7, 'cloude_parent', 101)
    child = info('ses_child', 8, 'cloude_child', 102)
    listed = [parent]
    calls: list[tuple] = []

    class View:

        app = SimpleNamespace(state=SimpleNamespace(session_manager=None))

        def fresh(self):
            return self

        async def list_session_infos(self):
            return list(listed)

        async def live_ids_now(self):
            return {one.session.id for one in listed}

    view = View()
    view.app.state.session_manager = view
    caller = AgentCaller('ses_parent', 'cloude_parent', 'ses_parent')
    body = spawn.SpawnRequest(provider='codex', task='fix the failing test',
                              working_dir=str(tmp_path), report_back=True)

    async def create(_request, request, **kwargs):
        calls.append(('create', request.agent_type, request.working_dir, kwargs['agent_extra_args']))
        listed.append(child)
        return SimpleNamespace(id='ses_child', working_dir=str(tmp_path))

    async def cards(_view, **_kwargs):
        return [{'id': 'ses_parent', 'session_uuid': 'uuid-parent', 'name': 'parent'},
                {'id': 'ses_child', 'session_uuid': 'uuid-child', 'name': 'child'}]

    async def send(_view, _caller, **kwargs):
        calls.append(('send', kwargs['to'], kwargs['expect_reply'], kwargs['owner_approved'], kwargs['text']))
        return {'id': 'm-1', 'thread': 't-1', 'status': 'queued'}

    async def park(_view, _caller, *_args):
        calls.append(('approved',))
        return await _args[-1](True)

    async def persist(_app, _parent, _child):
        calls.append(('layout',))
        return 'saved'

    monkeypatch.setattr(session_crud_routes, 'create_session_with_extra', create)
    monkeypatch.setattr(directory, 'list_cards', cards)
    monkeypatch.setattr(store, 'grant_contact', lambda *args, **kwargs: calls.append(('grant', *args, kwargs['source'])))
    monkeypatch.setattr(bus, 'send', send)
    monkeypatch.setattr(write_tools, 'park', park)
    monkeypatch.setattr(spawn_layout, 'persist', persist)
    monkeypatch.setattr(session_change_notice, 'publish', lambda *_args: 1)
    monkeypatch.setattr(beast_mode, 'approval_skip', lambda _action: False)
    from src.core.flow_data import spawn_links
    monkeypatch.setattr(spawn_links, 'record_quietly', lambda **kw: calls.append(('link', kw)))
    write_tools._created.clear()
    try:
        result = await spawn.spawn(view, caller, body)
    finally:
        write_tools._created.clear()
    assert result['id'] == 'ses_child'
    assert result['layout_status'] == 'saved'
    assert [call[0] for call in calls] == ['approved', 'create', 'grant', 'send', 'link', 'layout']
    link = calls[4][1]
    assert (link['child_id'], link['child_uuid'], link['parent_id'], link['parent_uuid'], link['parent_kind'], link['task_message_id']) == (
        'ses_child', 'uuid-child', 'ses_parent', 'uuid-parent', 'session', 'm-1')
    assert (link['parent_row_id'], link['child_row_id']) == (7, 8) if 'parent_row_id' in link else True
    assert calls[3][1:4] == ('ses_child', True, True)
    assert 'crosstalk_reply' in calls[3][4]


@pytest.mark.asyncio
async def test_spawn_defaults_to_parents_existing_folder(tmp_path) -> None:
    parent = info('ses_parent', 7, 'cloude_parent', 101)
    parent.session.working_dir = str(tmp_path)
    body = spawn.SpawnRequest(provider='claude', task='check the parser')
    assert await spawn._folder(body, parent) == str(tmp_path)
