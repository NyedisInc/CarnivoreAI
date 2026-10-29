from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from src.api.subagent_listing import mark_subagents
from src.core import single_flight
from src.core.db import connect, db_path_for
from src.core.provider_ledger import poller
from .activity import ActivityPoint
from .plugin.extract import project_key


def _epoch(value: datetime) -> float:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()


def _conversation_ids(state_dir: Any, infos: list[Any]) -> dict[int, str]:
    ids = [i.session_row_id for i in infos if i.session_row_id is not None]
    if not ids:
        return {}
    db = connect(db_path_for(state_dir))
    try:
        result = {}
        for offset in range(0, len(ids), 500):
            batch = ids[offset:offset + 500]
            rows = db.execute('SELECT id,claude_session_uuid FROM sessions WHERE id IN (' +
                              ','.join('?' for _ in batch) + ')', batch)
            result.update({row[0]: row[1] for row in rows if row[1]})
        return result
    finally:
        db.close()


async def sample(manager: Any, state_dir: Any) -> tuple[list[ActivityPoint], dict, list[dict], list[tuple[str, str, str]]]:
    flight = single_flight.flight_on(manager, single_flight.SESSION_LIST_FLIGHT_ATTR,
                                    single_flight.SESSION_LIST_FLIGHT_NAME)
    infos = await flight.run(manager.list_session_infos)
    mark_subagents(manager, infos)
    conversations = await asyncio.to_thread(_conversation_ids, state_dir, infos)
    now = datetime.now(timezone.utc)
    points: list[ActivityPoint] = []
    hints = []
    counts = dict(running_sessions=0, working_agents=0, waiting_agents=0,
                  idle_agents=0, unknown_agents=0, observed_subagents=0)
    subagents_known = True
    models: set[str] = set()
    projects: set[str] = set()
    for info in infos:
        row = info.session
        conversation = conversations.get(info.session_row_id, '')
        provider = info.agent_family or ''
        project = project_key(row.working_dir) if row.working_dir else ''
        observation = manager._attention_watcher.observation_for(row.id, now=now) if manager._attention_watcher else None
        fresh = observation is not None and not observation.stale and info.host_state == 'up'
        state = info.activity_status if fresh else 'unknown'
        running = (row.status.value == 'running' and state != 'dead') if info.host_state == 'up' else None
        counts['running_sessions'] += int(running is True)
        if state in ('working', 'working_subagent'):
            counts['working_agents'] += 1
        elif state in ('question', 'notice'):
            counts['waiting_agents'] += 1
        elif state in ('idle', 'finished_unread'):
            counts['idle_agents'] += 1
        elif state != 'dead':
            counts['unknown_agents'] += 1
        if info.subagents_running is None:
            subagents_known = False
        else:
            counts['observed_subagents'] += info.subagents_running
        if running and info.running_model:
            models.add(info.running_model)
        if running and project:
            projects.add(project)
        points.append(ActivityPoint(
            instance=f'{info.host_key}:{info.session_row_id or row.id}:{_epoch(row.created_at)}',
            conversation_id=conversation or f'session:{row.id}', provider=provider,
            project=project, model=info.running_model or '', host=info.host_key,
            state=state, observed_at=observation.observed_at.timestamp() if fresh else now.timestamp(),
            running=running, created_at=_epoch(row.created_at),
            subagents=info.subagents_running if fresh else None))
        if info.host_key == 'local' and conversation and provider in ('claude', 'codex'):
            hints.append((provider, conversation, row.working_dir))
    quota = []
    ledger = poller.snapshot()
    for account in ledger.accounts:
        if account.fetched_at is None or account.credential_state != 'ok':
            continue
        for window in account.windows:
            quota.append(dict(minute_ts=int(account.fetched_at.timestamp() // 60) * 60,
                              account_id=account.id, provider=account.provider, window=window.kind,
                              reset_at=window.resets_at.isoformat() if window.resets_at else '',
                              utilization=window.used_pct, fetched_at=account.fetched_at.isoformat(),
                              state=account.credential_state))
    live = dict(counts, observed_subagents=counts['observed_subagents'] if subagents_known else None,
                active_models=len(models), active_projects=len(projects),
                as_of=now.isoformat(), state='ok', activity_basis='sampled authoritative status',
                subagents_coverage='complete' if subagents_known else 'partial')
    return points, live, quota, hints
