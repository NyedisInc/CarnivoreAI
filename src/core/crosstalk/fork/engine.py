
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

import structlog
import websockets
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.crosstalk.fork import history
from src.core.crosstalk.spawn_rules import agent_cli_flags
from src.core.crosstalk.fork.replay import render_replay
from src.core.mcp.common import ToolError

logger = structlog.get_logger()


def _stamp_child(conn: sqlite3.Connection, *, row_id: int | None, socket: str,
                 tmux_name: str, epoch: int | None, parent_id: int) -> tuple[bool, str | None]:
    from src.core import session_fork
    from src.core.hosts.ddl import host_scope

    scope_sql, scope_params = host_scope(conn)
    row = conn.execute('''SELECT session_uuid FROM sessions
        WHERE id=? AND tmux_socket=? AND tmux_name=? AND tmux_created_epoch=?''' + scope_sql,
        (row_id, socket, tmux_name, epoch, *scope_params)).fetchone()
    child_uuid = str(row['session_uuid']) if row else None
    return (bool(child_uuid and session_fork.mark_as_fork(conn, child_session_uuid=child_uuid,
                                                        parent_id=parent_id)), child_uuid)


class ForkRequest(BaseModel):
    """Validated destination and optional continuation for one local fork."""

    model_config = ConfigDict(extra='forbid')
    source: str = Field(default='self', min_length=1, max_length=200)
    to_provider: Literal['claude', 'codex']
    model: str | None = Field(default=None, min_length=1, max_length=200)
    effort: Literal['low', 'medium', 'high', 'xhigh', 'max'] | None = None
    prompt: str | None = Field(default=None, min_length=1, max_length=19000)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    worktree: bool = False

    @model_validator(mode='after')
    def validate_model(self) -> 'ForkRequest':
        if self.model is not None:
            from src.models.model_ids import describe_model_id_rejection, is_valid_model_id
            if not is_valid_model_id(self.model):
                raise ValueError(describe_model_id_rejection(self.model))
        if self.to_provider == 'claude' and self.effort in ('xhigh', 'max'):
            raise ValueError('claude effort is low, medium or high')
        if self.prompt is not None and len(self.prompt.encode('utf-8')) > 4000:
            raise ValueError('fork continuation prompt is at most 4000 bytes')
        return self


async def _source(view: Any, caller: Any, source_id: str, owner_approved: bool) -> Any:
    is_self = source_id == 'self'
    if is_self:
        if owner_approved or caller.external:
            raise ToolError('source=self needs an authenticated local pane')
        source_id = caller.current_session_id
    info = next((item for item in await view.list_session_infos() if item.session.id == source_id), None)
    if info is None or info.host_key != 'local' or not info.tmux_session:
        raise ToolError('source must be an exact local live session id; cross-machine fork is unavailable')
    if is_self and (caller.current_session_id != source_id or caller.tmux_name != info.tmux_session):
        raise ToolError('source=self no longer matches the authenticated pane')
    if (info.agent_family or info.agent_type or info.session.agent_type) not in ('claude', 'codex'):
        raise ToolError('source provider must be claude or codex')
    return info


def _conversation(info: Any) -> tuple[str, int, str]:
    from src.config import settings
    from src.core.db import connect, db_path_for

    row_id = info.session_row_id
    if not isinstance(row_id, int):
        raise ToolError('source has no durable session row')
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        row = conn.execute('SELECT id, session_uuid, claude_session_uuid, tmux_created_epoch FROM sessions WHERE id = ?',
                           (row_id,)).fetchone()
    if row is None or row['tmux_created_epoch'] != info.session.tmux_created_epoch:
        raise ToolError('source session row changed before fork')
    conversation = row['claude_session_uuid']
    if not conversation:
        raise ToolError('source has no recorded conversation to fork')
    return str(conversation), int(row['id']), str(row['session_uuid'])


async def fork(view: Any, caller: Any, body: ForkRequest, *, owner_approved: bool = False) -> dict:
    from src.core.mcp import beast_mode, write_tools

    parent = await _source(view, caller, body.source, owner_approved)
    parent_id = parent.session.id
    parent_epoch = parent.session.tmux_created_epoch
    source_provider = parent.agent_family or parent.agent_type or parent.session.agent_type
    summary = f'fork {parent_id} from {source_provider} to {body.to_provider}'
    from src.core.crosstalk.bus import caller_identity
    requested_by = None if owner_approved else await caller_identity(view, caller)

    async def run(_approved: bool) -> dict:
        from src.api.session_crud_routes import create_session_with_extra
        from src.core.crosstalk import spawn_layout
        from src.core.crosstalk.fork import claude_to_codex, codex_to_claude
        from src.core.mcp.write_tools import _create_lock, _created, _created_counts, _request, _via_route
        from src.models import CreateSessionRequest

        fresh = view.fresh()
        again = next((item for item in await fresh.list_session_infos() if item.session.id == parent_id), None)
        if again is None or again.session.tmux_created_epoch != parent_epoch or again.tmux_session != parent.tmux_session:
            raise ToolError('source pane changed while fork waited; nothing was created')
        conversation, row_id, contact_key = await asyncio.to_thread(_conversation, again)
        if owner_approved:
            initiator = {'key': contact_key, 'epoch': parent_epoch}
        else:
            initiator = await caller_identity(fresh, caller)
            if (initiator['key'], initiator['epoch']) != (requested_by['key'], requested_by['epoch']):
                raise ToolError('requesting pane changed while fork waited; nothing was created')
        folder = os.path.realpath(os.path.expanduser(again.session.working_dir or ''))
        if not os.path.isdir(folder):
            raise ToolError('source working directory is unavailable')
        data, source_path = await asyncio.to_thread(history.transcript_bytes, source_provider, conversation, folder)
        parts = await asyncio.to_thread(history.replay_parts, source_provider, data)
        from src.core.account_switch.launch_env import new_pane_env
        account_env = await new_pane_env({})
        claude_root = Path(account_env.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').expanduser() / 'projects'
        codex_root = Path(account_env.get('CODEX_HOME') or Path.home() / '.codex').expanduser() / 'sessions'
        beast = beast_mode.approval_skip('agent_fork')
        async with _create_lock:
            mine, total = _created_counts(await fresh.live_ids_now(), caller, time.monotonic())
            if mine >= write_tools.MAX_CREATED_PER_AGENT or total >= write_tools.MAX_CREATED_TOTAL:
                raise ToolError('agent-created session limit reached')
            target_folder = folder
            if body.worktree:
                from src.core.crosstalk.spawn import _worktree
                target_folder = await _worktree(folder, body.name or 'fork')
            native = False
            extra: list[str] = []
            created_transcript: Path | None = None
            if (source_provider == body.to_provider == 'claude' and not body.worktree and source_path is not None
                    and source_path.resolve().is_relative_to(claude_root.resolve())):
                extra = ['--resume', conversation, '--fork-session']
                native = True
            elif (source_provider == body.to_provider == 'codex' and source_path is not None
                    and source_path.resolve().is_relative_to(codex_root.resolve())):
                extra = ['fork', conversation]
                native = True
            elif body.to_provider == 'claude':
                target, created_transcript = await asyncio.to_thread(
                    codex_to_claude.write, parts, cwd=target_folder,
                    profile=account_env.get('CLAUDE_CONFIG_DIR'))
                extra = ['--resume', target]
                native = True
            elif source_provider == 'claude' and body.to_provider == 'codex':
                try:
                    target = await claude_to_codex.import_session(data, conversation=conversation, cwd=target_folder,
                                                                  codex_home=account_env.get('CODEX_HOME'))
                    extra = ['resume', target]
                    native = True
                except (OSError, TimeoutError, ValueError, RuntimeError,
                        websockets.WebSocketException) as exc:
                    logger.warning('crosstalk_fork_native_import_failed', error_type=type(exc).__name__)
            opening = body.prompt
            if not native:
                suffix = ('\nContinue with this request: ' + body.prompt) if body.prompt else ''
                replay = await asyncio.to_thread(render_replay, parts, max_bytes=8192 - len(suffix.encode('utf-8')))
                opening = replay.text + suffix
            extra += agent_cli_flags(body.to_provider, body.effort, beast)
            if body.to_provider == 'codex':
                extra += ['--cd', target_folder]
            request = CreateSessionRequest(working_dir=target_folder, agent_type=body.to_provider,
                                           project_name=os.path.basename(target_folder),
                                           label=body.name or f'{again.label or again.tmux_session}(fork)',
                                           model=body.model, opening_prompt=opening)
            try:
                child = await _via_route(create_session_with_extra(_request(fresh), request, agent_extra_args=extra))
            except (ToolError, ValueError, RuntimeError, HTTPException, OSError):
                if created_transcript is not None:
                    created_transcript.unlink(missing_ok=True)
                raise
            _created[child.id] = (caller.tmux_name, time.monotonic())
        child_info = next((item for item in await fresh.fresh().list_session_infos() if item.session.id == child.id), None)
        if child_info is None or not child_info.tmux_session:
            raise ToolError(f'fork {child.id} started, but its pane is not listed yet')
        from src.core import session_change_notice
        from src.core.db import connect, db_path_for, transaction
        from src.config import settings

        def stamp() -> tuple[bool, str | None]:
            with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
                with transaction(conn):
                    return _stamp_child(conn, row_id=child_info.session_row_id,
                        socket=fresh._manager.tmux_socket_name(), tmux_name=child_info.tmux_session,
                        epoch=child_info.session.tmux_created_epoch, parent_id=row_id)

        lineage, child_uuid = await asyncio.to_thread(stamp)
        from src.core.crosstalk import store
        if lineage and child_uuid:
            await asyncio.to_thread(store.grant_contact, initiator['key'], child_uuid,
                                    initiator['epoch'], child_info.session.tmux_created_epoch, source='fork')
        layout = await spawn_layout.persist(view.app, again, child_info)
        session_change_notice.publish(view.app.state, {'type': 'agent.forked', 'parent': parent_id,
            'session_id': child.id, 'name': request.label, 'layout_status': layout})
        logger.info('crosstalk_agent_forked', parent_id=parent_id, child_id=child.id,
                    source_provider=source_provider, to_provider=body.to_provider, native=native)
        return {'id': child.id, 'parent': parent_id, 'provider': body.to_provider,
                'mode': 'native' if native else 'replay', 'working_dir': target_folder,
                'lineage_recorded': lineage, 'layout_status': layout}

    if owner_approved:
        return await run(True)
    if beast_mode.approval_skip('agent_fork'):
        return await beast_mode.run_unprompted(caller, 'agent_fork', lambda: run(True),
            target_id=parent_id, target_tmux=parent.tmux_session, summary=summary,
            args=body.model_dump(exclude_none=True))
    return await write_tools.park(view, caller, parent_id, parent.tmux_session,
        'agent_fork', summary, body.model_dump(exclude_none=True), run)
