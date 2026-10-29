
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.crosstalk import bus, directory, store
from src.core.flow_data import spawn_links
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError

logger = structlog.get_logger()


class SpawnRequest(BaseModel):
    """Validated owner or MCP request to create one local agent and assign work."""

    model_config = ConfigDict(extra='forbid')

    provider: Literal['claude', 'codex']
    task: str = Field(min_length=1, max_length=19000)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    effort: Literal['low', 'medium', 'high', 'xhigh', 'max'] | None = None
    project: str | None = Field(default=None, min_length=1, max_length=200)
    working_dir: str | None = Field(default=None, min_length=1, max_length=4096)
    worktree: bool = False
    report_back: bool = True
    parent: str | None = Field(default=None, min_length=1, max_length=200)
    peer: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode='after')
    def _one_folder(self) -> 'SpawnRequest':
        if self.project is not None and self.working_dir is not None:
            raise ValueError('give only one of project or working_dir')
        if self.model is not None:
            from src.models.model_ids import describe_model_id_rejection, is_valid_model_id
            if not is_valid_model_id(self.model):
                raise ValueError(describe_model_id_rejection(self.model))
        return self


def _sender_key(card: dict) -> str:
    return str(card.get('session_uuid') or card['id'])


async def _folder(body: SpawnRequest, parent: Any | None) -> str:
    from src.core.mcp.write_tools import _project_path

    path = (await _project_path(body.project) if body.project else body.working_dir or
            (parent.session.working_dir if parent else None))
    if not path:
        raise ToolError('the parent has no working directory; give project or working_dir')
    real = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(real):
        raise ToolError('working_dir is not an existing directory')
    return real


async def _worktree(path: str, name: str) -> str:
    from src.config import settings
    from src.core import project_worktree

    code, repo, _ = await project_worktree.run_git(['-C', path, 'rev-parse', '--show-toplevel'])
    if code != 0 or not repo:
        raise ToolError('worktree needs a git repository')
    code, branch, _ = await project_worktree.run_git(['-C', repo, 'symbolic-ref', '--quiet', '--short', 'HEAD'])
    if code != 0 or not branch:
        raise ToolError('worktree needs a checked-out branch')
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-.')[:48] or 'agent'
    target_branch = f'agent/{slug}-{hashlib.sha256(os.urandom(16)).hexdigest()[:8]}'
    root = project_worktree.read_root(settings.auth_config_file)
    try:
        plan = await project_worktree.plan_worktree(repo, branch, target_branch, root=root)
        await project_worktree.create_worktree(plan, root=root)
    except (project_worktree.WorktreeRefused, project_worktree.WorktreeTimeout,
            project_worktree.GitUnavailable) as exc:
        raise ToolError(f'worktree refused: {exc}') from exc
    return plan.path


def _flags(body: SpawnRequest, beast: bool) -> list[str]:
    flags: list[str] = []
    if body.effort:
        flags.extend(['-c', f'model_reasoning_effort="{body.effort}"'] if body.provider == 'codex'
                     else ['--effort', body.effort])
    if beast and body.provider == 'codex':
        flags.append('--dangerously-bypass-approvals-and-sandbox')
    return flags


async def spawn(view: Any, caller: AgentCaller, body: SpawnRequest, *, owner_approved: bool = False) -> dict:
    from src.core.mcp import beast_mode, write_tools
    from src.core.mcp.protocol import BatchView

    if body.parent and not owner_approved:
        raise ToolError('parent is for the owner route only')
    if body.provider == 'claude' and body.effort in ('xhigh', 'max'):
        raise ToolError('claude effort is low, medium or high')
    if body.peer is not None:
        from src.core.crosstalk import spawn_remote
        return await spawn_remote.spawn(view, caller, body, owner_approved=owner_approved)
    parent_id = body.parent or caller.current_session_id
    infos = await view.list_session_infos()
    parent = next((info for info in infos if info.session.id == parent_id), None)
    if parent is None and not caller.external:
        raise ToolError('parent session is not a live local pane')
    if parent is not None and not parent.tmux_session:
        raise ToolError('parent session is not a live local pane')
    if parent is not None and not owner_approved and not caller.external and (
            parent.tmux_session != caller.tmux_name or parent.session.id != caller.current_session_id):
        raise ToolError('the authenticated caller is not the parent pane')
    if parent is None and body.project is None and body.working_dir is None:
        raise ToolError('external spawn needs project or working_dir')
    folder = await _folder(body, parent)
    parent_epoch = parent.session.tmux_created_epoch if parent else None
    summary = f"spawn {body.provider} in {folder} for: {body.task[:160]}"
    shown = body.model_dump(exclude_none=True)
    task = body.task
    if body.report_back:
        task += ('\n\nWhen the requested work is complete, report the actual outcome to your '
                 'parent with crosstalk_reply on this message. Include what changed, checks, and blockers.')
    from src.core.session_one_shot_gate import MAX_BODY_BYTES
    if len(task) > store.MAX_TEXT or len(task.encode('utf-8')) + 1024 > MAX_BODY_BYTES:
        raise ToolError('task exceeds the crosstalk delivery limit')
    if any((ord(char) < 32 and char not in '\n\t') or 127 <= ord(char) <= 159 for char in task):
        raise ToolError('task contains control characters the delivery guard would alter')

    async def run(_approved: bool) -> dict:
        from src.api.session_crud_routes import create_session_with_extra
        from src.core.mcp.write_tools import (_create_lock, _created, _created_counts,
                                              _request, _via_route)
        from src.models import CreateSessionRequest

        fresh = view.fresh()
        again = next((info for info in await fresh.list_session_infos() if info.session.id == parent_id), None)
        if parent is not None and (again is None or again.session.tmux_created_epoch != parent_epoch
                                   or again.tmux_session != parent.tmux_session):
            raise ToolError('the parent is now a different pane; nothing was spawned')
        beast = beast_mode.approval_skip('agent_spawn')
        async with _create_lock:
            listed_at = time.monotonic()
            mine, total = _created_counts(await fresh.live_ids_now(), caller, listed_at)
            if mine >= write_tools.MAX_CREATED_PER_AGENT:
                raise ToolError(f'you already have {mine} live sessions you created (limit {write_tools.MAX_CREATED_PER_AGENT})')
            if total >= write_tools.MAX_CREATED_TOTAL:
                raise ToolError(f'{total} agent-created sessions are live (limit {write_tools.MAX_CREATED_TOTAL})')
            target_dir = await _worktree(folder, body.name or body.provider) if body.worktree else folder
            request = CreateSessionRequest(working_dir=target_dir, agent_type=body.provider,
                                           project_name=os.path.basename(target_dir),
                                           label=body.name, model=body.model)
            created = await _via_route(create_session_with_extra(_request(fresh), request,
                                                                 agent_extra_args=_flags(body, beast)))
            _created[created.id] = (caller.tmux_name, time.monotonic())
        cards = await directory.list_cards(BatchView(view.app.state.session_manager, view.app),
                                           self_tmux=again.tmux_session if again else None,
                                           include_remote=False)
        sender = next((card for card in cards if card['id'] == parent_id), None)
        receiver = next((card for card in cards if card['id'] == created.id), None)
        if (sender is None and not caller.external) or receiver is None:
            raise ToolError(f'session {created.id} started, but the task is pending directory discovery')
        receiver_info = next((info for info in await fresh.fresh().list_session_infos()
                              if info.session.id == created.id), None)
        if receiver_info is None:
            raise ToolError(f'session {created.id} started, but its pane is not listed yet')
        sender_key = caller.current_session_id if caller.external else _sender_key(sender)
        sender_epoch = None if caller.external else parent_epoch
        await asyncio.to_thread(store.grant_contact, sender_key, _sender_key(receiver),
                                sender_epoch, receiver_info.session.tmux_created_epoch, source='spawn')
        message = await bus.send(fresh.fresh(), caller, to=created.id, text=task,
                                 expect_reply=body.report_back, owner_approved=True,
                                 action='agent_spawn')
        await asyncio.to_thread(
            spawn_links.record_quietly, child_id=created.id, child_uuid=receiver.get('session_uuid'), parent_id=parent_id,
            parent_uuid=None if sender is None else sender.get('session_uuid'),
            parent_kind=spawn_links.KIND_EXTERNAL if caller.external else spawn_links.KIND_SESSION,
            task_message_id=message.get('id') if isinstance(message, dict) else None,
            parent_row_id=None if again is None else again.session_row_id, child_row_id=receiver_info.session_row_id)
        from src.core.crosstalk import spawn_layout
        from src.core import session_change_notice
        layout_status = await spawn_layout.persist(view.app, again, receiver_info) if again else 'external_client'
        session_change_notice.publish(view.app.state, {
            'type': 'agent.spawned', 'parent': parent_id, 'session_id': created.id,
            'name': receiver['name'], 'layout_status': layout_status,
        })
        logger.info('crosstalk_agent_spawned', parent_id=parent_id, session_id=created.id,
                    provider=body.provider, worktree=body.worktree, layout_status=layout_status)
        return {'id': created.id, 'parent': parent_id, 'working_dir': target_dir,
                'task_message': message, 'report_back': body.report_back,
                'startup_gate': receiver_info.startup_gate, 'layout_status': layout_status}

    if owner_approved:
        return await run(True)
    if beast_mode.approval_skip('agent_spawn'):
        return await beast_mode.run_unprompted(caller, 'agent_spawn', lambda: run(True),
                                                target_id=parent_id, target_tmux=parent.tmux_session if parent else '',
                                                summary=summary, args=shown)
    return await write_tools.park(view, caller, parent_id, parent.tmux_session if parent else '',
                                  'agent_spawn', summary, shown, run)
