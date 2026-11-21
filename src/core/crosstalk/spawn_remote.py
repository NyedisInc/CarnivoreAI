
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.core.crosstalk import bus, spawn_rules
from src.core.federation import peer_links
from src.core.flow_data import spawn_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.hosts.identity import remote_session_id
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError


def same_created_child(child: Any, created: dict, peer_install_id: str, *, epoch_known: bool = True) -> bool:
    from src.core.federation import shadow_rows
    expected_uuid = created.get('session_uuid')
    return (child is not None and isinstance(expected_uuid, str) and bool(expected_uuid)
            and child.session_uuid == shadow_rows.shadow_uuid(peer_install_id, expected_uuid)
            and (not epoch_known or child.session.tmux_created_epoch == created.get('epoch')))


@dataclass
class AutoPlan:

    plan: Any
    starter: Any
    req: Any
    folder: str
    rid: str


async def prepare_auto(view: Any, caller: AgentCaller, body: Any, folder: str) -> AutoPlan:
    from src.core.mcp import place_args
    from src.core.pack.session_place import same_file

    stays = ('a new worktree stays on this computer' if body.worktree
             else 'an effort setting stays on this computer' if body.effort else None)
    if stays is None:
        stays = await same_file.reason_for(folder, f"{body.task}\n{body.name or ''}")
    starter = await place_args.starter_for(view.app, caller, model=body.model)
    req = place_args.place_request(folder, body.provider, body.needs)
    return AutoPlan(await place_args.plan_for(view.app, req, stays), starter, req, folder, uuid.uuid4().hex)


async def _placed_create(view: Any, caller: AgentCaller, body: Any, auto: AutoPlan, parent_id: str, parent_epoch: Any, again: Any, task: str) -> tuple:
    from src.api.session_crud_routes import create_session_with_extra
    from src.core.crosstalk import spawn, spawn_rules
    from src.core.mcp import beast_mode, write_tools
    from src.core.pack.jobs.types import JobError
    from src.core.pack.session_place import create as create_mod
    from src.models import CreateSessionRequest

    fresh = view.fresh()
    request = CreateSessionRequest(working_dir=auto.folder, agent_type=body.provider, project_name=os.path.basename(auto.folder), label=body.name,
                                   model=body.model)

    async def local(create_body: Any) -> Any:
        flags = spawn_rules.agent_cli_flags(body.provider, body.effort, beast_mode.approval_skip('agent_spawn'))
        return await write_tools._via_route(create_session_with_extra(write_tools._request(fresh), create_body, agent_extra_args=flags))

    try:
        placed = await create_mod.create_placed(view.app, auto.req, auto.starter, request, local_create=local, request_id=auto.rid, approved=auto.plan)
    except JobError as exc:
        raise ToolError(f'{exc.code}: {exc.detail}') from exc
    if placed.placement.get('decision') == 'here':
        write_tools._created[placed.session.id] = (caller.tmux_name, time.monotonic())
        done = await spawn.finish_local(view, caller, body, parent_id=parent_id, parent_epoch=parent_epoch, again=again, created=placed.session,
                                        target_dir=auto.folder, task=task, extra={'placement': placed.placement})
        return done, None
    return placed, placed.session['id']


def peer_spawn_payload(body: Any, beast: bool) -> dict:
    payload = body.model_dump(exclude={'peer', 'parent', 'placement', 'needs'}, exclude_none=True)
    payload['beast'] = beast
    return payload


async def spawn(view: Any, caller: AgentCaller, body: Any, *, owner_approved: bool, auto: AutoPlan | None = None) -> dict:
    from src.core.mcp import beast_mode, federated, place_args, write_tools

    if caller.external:
        raise ToolError('remote agent spawn needs a local parent pane')
    if auto is None and body.working_dir is None and body.project is None:
        raise ToolError('remote spawn needs a working_dir or project on that computer')
    if auto is None:
        peer = await federated.find_peer(body.peer)
    else:
        from src.core.pack.session_place import create as create_mod
        peer = await asyncio.to_thread(create_mod._peer, auto.plan.install_id)  # noqa: SLF001
    parent_id = body.parent or caller.current_session_id
    parent = next((i for i in await view.list_session_infos() if i.session.id == parent_id), None)
    if parent is None or not parent.tmux_session:
        raise ToolError('parent session is not a live local pane')
    if not owner_approved and (parent.tmux_session != caller.tmux_name or parent_id != caller.current_session_id):
        raise ToolError('the authenticated caller is not the parent pane')
    parent_epoch = parent.session.tmux_created_epoch
    task = spawn_rules.task_with_report_back(body.task, body.report_back)
    spawn_rules.validate_paste_text(task)
    summary = f'on {peer.label}: spawn {body.provider} in {body.working_dir or body.project} for: {body.task[:160]}'
    shown = body.model_dump(exclude_none=True, exclude=None if auto else {'placement', 'needs'})
    if auto is not None:
        summary = place_args.summary_of(auto.plan, f'spawn {body.provider} in {auto.folder} for: {body.task[:160]}')
        shown = place_args.card_args(auto.plan, auto.starter, shown)

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
        links = peer_links.LINKS
        try:
            if auto is not None:
                got, wire_id = await _placed_create(view, caller, body, auto, parent_id, parent_epoch, again, task)
                if wire_id is None:
                    return got
                created = {'session_uuid': got.session.get('session_uuid'), 'tmux_name': got.session.get('tmux_session'),
                           'working_dir': got.session.get('working_dir'),
                           **({'epoch': got.session['epoch']} if 'epoch' in got.session else {})}
            else:
                client = links.client(peer.peer_install_id) if links is not None else None
                if client is None:
                    raise ToolError(f'{peer.label} is not connected right now')
                payload = peer_spawn_payload(body, beast_mode.approval_skip('agent_spawn'))
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
        if not same_created_child(child, created, peer.peer_install_id, epoch_known='epoch' in created):
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
                                      'session_id': wire_id, 'name': body.name or created.get('tmux_name'), 'layout_status': layout_status})
        result = {'id': wire_id, 'parent': parent_id, 'working_dir': created.get('working_dir'),
                  'task_message': message, 'report_back': body.report_back, 'layout_status': layout_status}
        if auto is not None:
            result['placement'] = got.placement
        return result

    if owner_approved:
        return await run(True)
    if beast_mode.approval_skip('agent_spawn'):
        return await beast_mode.run_unprompted(caller, 'agent_spawn', lambda: run(True),
            target_id=f'remote:{peer.key}:new', target_tmux='', summary=summary, args=shown)
    return await write_tools.park(view, caller, f'remote:{peer.key}:new', '', 'agent_spawn', summary, shown, run)
