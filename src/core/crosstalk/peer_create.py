
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from fastapi import Request

from src.core.crosstalk import directory
from src.models import CreateSessionRequest


class PeerCreateRefused(RuntimeError):

    def __init__(self, code: str, status: int = 503) -> None:
        super().__init__(code)
        self.code, self.status = code, status


async def create_pane(request: Request, *, target_dir: str, agent_type: str, label: Optional[str], model: Optional[str],
                      extra_args: List[str], extra_env: Optional[Dict[str, str]] = None) -> dict:
    from src.api.session_crud_routes import create_session_with_extra

    created = await create_session_with_extra(request,
        CreateSessionRequest(working_dir=target_dir, agent_type=agent_type, project_name=target_dir.rsplit('/', 1)[-1],
                             label=label, model=model), agent_extra_args=extra_args, extra_env=extra_env)
    info = await request.app.state.session_manager.get_session_info(session_id=created.id)
    if info is None or not info.tmux_session or info.session_row_id is None:
        raise PeerCreateRefused('created_session_not_listed')
    details = await asyncio.to_thread(directory._session_details, [info.session_row_id])
    durable_uuid = details.get(info.session_row_id, (None,))[0]
    if not durable_uuid:
        raise PeerCreateRefused('created_session_not_listed')
    return {'id': created.id, 'tmux_name': info.tmux_session, 'working_dir': target_dir,
            'epoch': info.session.tmux_created_epoch, 'session_uuid': durable_uuid, 'row_id': int(info.session_row_id)}
