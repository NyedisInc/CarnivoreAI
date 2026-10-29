
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Iterator, List, Optional, Sequence

from src.core.mcp_health.fold import McpHealth
from src.cplugs.sdk import ports
from src.cplugs.sdk.mcp_health import PORT_NAME


class StubPort:

    def health_for(self, app_state: Any, row: Any, now: Any) -> Optional[McpHealth]:
        return getattr(app_state.session_manager, "health", None)

    def stamp(self, app_state: Any, rows: Sequence[Any], now: Any) -> List[Optional[McpHealth]]:
        return [self.health_for(app_state, row, now) for row in rows]


def app_state(manager: Any = None) -> Any:
    return SimpleNamespace(session_manager=manager)


@contextmanager
def plugin_on() -> Iterator[StubPort]:
    port = StubPort()
    ports.register(PORT_NAME, port)
    try:
        yield port
    finally:
        ports.unregister(PORT_NAME)
