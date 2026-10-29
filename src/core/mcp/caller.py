
from __future__ import annotations

from dataclasses import dataclass

TOKEN_ID_PREFIX = "mcp-token:"


@dataclass(frozen=True)
class AgentCaller:

    session_id: str
    tmux_name: str
    current_session_id: str
    token_name: str = ""
    scope: str = "write"
    proxied_agent_id: int = 0

    @property
    def external(self) -> bool:
        return bool(self.token_name)

    @property
    def from_token(self) -> bool:
        return self.external or self.session_id.startswith(TOKEN_ID_PREFIX)
