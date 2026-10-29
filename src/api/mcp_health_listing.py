
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.core.mcp_health.fold import McpHealth
from src.cplugs.sdk import ports
from src.cplugs.sdk.mcp_health import PORT_NAME
from src.models import CarnivoreLinkInfo, McpDropInfo, McpHealthInfo, SessionInfo
from src.models.sessions import McpServerHealthInfo


def mcp_health_info(health: Optional[McpHealth]) -> Optional[McpHealthInfo]:
    if health is None:
        return None
    link = health.carnivore
    return McpHealthInfo(
        servers=[
            McpServerHealthInfo(name=s.name, transport=s.transport, state=s.state, reason=s.reason, source=s.source,
                                detail=s.detail, at=s.at.isoformat() if s.at else None, exact=s.exact)
            for s in health.servers
        ],
        dropped=[
            McpDropInfo(name=d.name, state=d.state, at=d.at.isoformat() if d.at else None, exact=d.exact, source=d.source)
            for d in health.dropped
        ],
        carnivore=None if link is None else CarnivoreLinkInfo(
            state=link.state,
            initialized_at=link.initialized_at.isoformat() if link.initialized_at else None,
            last_request_at=link.last_request_at.isoformat() if link.last_request_at else None,
        ),
    )


def mcp_health_for_row(app_state: Any, info: Any, now: Optional[datetime] = None) -> Optional[McpHealth]:
    port = ports.get(PORT_NAME)
    return port.health_for(app_state, info, now or datetime.now(timezone.utc)) if port is not None else None


def mark_mcp_health(app_state: Any, infos: Iterable[Any]) -> None:
    rows = [i for i in infos if isinstance(i, SessionInfo)]
    port = ports.get(PORT_NAME)
    found = port.stamp(app_state, rows, datetime.now(timezone.utc)) if port is not None else [None] * len(rows)
    for row, health in zip(rows, found):
        row.mcp_health = mcp_health_info(health)
