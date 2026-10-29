
from __future__ import annotations

import asyncio
import time
from typing import Any

from src.core.crosstalk import bus, store
from src.core.federation import peer_links
from src.core.flow_data import spawn_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.hosts.identity import remote_session_id
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError


def same_created_child(child: Any, created: dict, peer_install_id: str) -> bool:
    from src.core.federation import shadow_rows
    expected_uuid = created.get('session_uuid')
    return (child is not None and isinstance(expected_uuid, str) and bool(expected_uuid)
            and child.session_uuid == shadow_rows.shadow_uuid(peer_install_id, expected_uuid)
            and child.session.tmux_created_epoch == created.get('epoch'))


async def spawn(view: Any, caller: AgentCaller, body: Any, *, owner_approved: bool) -> dict:
    from src.core.mcp import beast_mode, federated, write_tools

    if caller.external:
        raise ToolError('remote agent spawn needs a local parent pane')
    if body.working_dir is None and body.project is None:
        raise ToolError('remote spawn needs a working_dir or project on that computer')
    peer = await federated.find_peer(body.peer)
    parent_id = body.parent or caller.current_session_id
    parent = next((i for i in await view.list_session_infos() if i.session.id == parent_id), None)
    if parent is None or not parent.tmux_session:
        raise ToolError('parent session is not a live local pane')
    if not owner_approved and (parent.tmux_session != caller.tmux_name or parent_id != caller.current_session_id):
        raise ToolError('the authenticated caller is not the parent pane')
    parent_epoch = parent.session.tmux_created_epoch
    task = body.task + (('\n\nWhen the work is complete, report the actual outcome to your parent with '
                         'crosstalk_reply on this message. Include changes, checks, and blockers.') if body.report_back else '')
    from src.core.session_one_shot_gate import MAX_BODY_BYTES
    if len(task) > store.MAX_TEXT or len(task.encode('utf-8')) + 1024 > MAX_BODY_BYTES:
        raise ToolError('task exceeds the crosstalk delivery limit')
    if any((ord(c) < 32 and c not in '\n\t') or 127 <= ord(c) <= 159 for c in task):
        raise ToolError('task contains control characters the delivery guard would alter')
    summary = f'on {peer.label}: spawn {body.provider} in {body.working_dir or body.project} for: {body.task[:160]}'
    shown = body.model_dump(exclude_none=True)

    async def run(_approved: bool) -> dict:
        fresh = view.fresh()
        again = next((i for i in await fresh.list_session_infos() if i.session.id == parent_id), None)
        if again is None or again.session.tmux_created_epoch != parent_epoch or again.tmux_session != parent.tmux_session:
            raise ToolError('the parent is now a different pane; nothing was spawned')
        async with write_tools._create_lock:
            mine, total = write_tools._created_counts(await fresh.live_ids_now(), caller, time.monotonic())
            if mine >= write_tools.MAX_CREATED_PER_AGENT:
                raise ToolError(f'you already have {mine} live sessions you created (limit {write_tools.MAX_CREATED_PER_AGENT})')
            if total >= write_tools.MAX_CREATED_TOTAL:
                raise ToolError(f'{total} agent-created sessions are live (limit {write_tools.MAX_CREATED_TOTAL})')
            write_tools._reserved.append(caller.tmux_name)
        try:
            links = peer_links.LINKS
            client = links.client(peer.peer_install_id) if links is not None else None
            if client is None:
                raise ToolError(f'{peer.label} is not connected right now')
            payload = body.model_dump(exclude={'peer', 'parent'}, exclude_none=True)
            payload['beast'] = beast_mode.approval_skip('agent_spawn')
            try:
                answer = await client.request('POST', '/api/v1/crosstalk/peer-spawn', json=payload, timeout=45)
            except (PeerUnreachable, PeerRefused) as exc:
                raise ToolError(f'{peer.label} did not confirm spawn; inspect its sessions before retrying ({type(exc).__name__})') from exc
            if answer.status_code != 200:
                raise ToolError(f'{peer.label} refused spawn ({answer.status_code})')
            created = answer.json()
            tmux = created.get('tmux_name')
            if not isinstance(tmux, str) or not tmux:
                raise ToolError(f'{peer.label} created a pane but did not return its tmux identity')
            wire_id = remote_session_id(peer.key, tmux)
            write_tools._created[wire_id] = (caller.tmux_name, time.monotonic())
        finally:
            async with write_tools._create_lock:
                write_tools._reserved.remove(caller.tmux_name)
        from src.api import peer_auth
        from src.core.federation import peer_listing
        await peer_listing.refresh(peer, links, peer_auth.open_db, force=True)
        child = next((i for i in await federated.peer_infos(force=True) if i.session.id == wire_id), None)
        if not same_created_child(child, created, peer.peer_install_id):
            raise ToolError(f'{wire_id} was created but its pane identity was not confirmed for task delivery')
        try:
            message = await bus.send(fresh.fresh(), caller, to=wire_id, text=task,
                                     expect_reply=body.report_back, owner_approved=True, action='agent_spawn')
        except ToolError as exc:
            raise ToolError(f'{wire_id} was created but its task is pending: {exc}') from exc
        await asyncio.to_thread(
            spawn_links.record_quietly, child_id=wire_id, child_uuid=child.session_uuid, parent_id=parent_id,
            parent_uuid=parent.session_uuid, parent_kind=spawn_links.KIND_SESSION,
            task_message_id=message.get('id') if isinstance(message, dict) else None, peer_install_id=peer.peer_install_id)
        from src.core import session_change_notice
        from src.core.crosstalk import spawn_layout
        layout_status = await spawn_layout.persist(view.app, again, child)
        session_change_notice.publish(view.app.state, {'type': 'agent.spawned', 'parent': parent_id,
                                      'session_id': wire_id, 'name': body.name or tmux, 'layout_status': layout_status})
        return {'id': wire_id, 'parent': parent_id, 'working_dir': created.get('working_dir'),
                'task_message': message, 'report_back': body.report_back, 'layout_status': layout_status}

    if owner_approved:
        return await run(True)
    if beast_mode.approval_skip('agent_spawn'):
        return await beast_mode.run_unprompted(caller, 'agent_spawn', lambda: run(True),
            target_id=f'remote:{peer.key}:new', target_tmux='', summary=summary, args=shown)
    return await write_tools.park(view, caller, f'remote:{peer.key}:new', '', 'agent_spawn', summary, shown, run)
