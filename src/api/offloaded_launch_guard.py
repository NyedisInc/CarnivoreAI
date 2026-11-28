
from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException

from src.core.hosts.ddl import LOCAL_HOST_KEY


def refuse_offloaded_resume(host_key: str, agent_extra_args: Optional[List[str]]) -> None:
    if host_key != LOCAL_HOST_KEY or not agent_extra_args:
        return
    from src.core.backup_health import offload_guard

    off = offload_guard.resumed_offloaded(agent_extra_args)
    if off is not None:
        raise HTTPException(status_code=409, detail=offload_guard.refusal_body(off))
