
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from src.config.agents import AgentsConfig
from src.config.auth import AuthConfig
from src.core.agent_families import build_family_summaries


def family_summaries(
    agents: AgentsConfig, agent_command: Callable[..., str]
) -> List[dict]:
    return build_family_summaries(agents, agent_command)


def settings_summary(
    config: AuthConfig,
    *,
    host: Optional[str],
    port: int,
    families: List[dict],
    bound_host: Optional[str],
) -> Dict[str, Any]:
    agents = config.agents
    wildcard_bind = host in ("0.0.0.0", "", None)
    return {
        "agents": {
            "wrappers": [w.model_dump() for w in agents.wrappers],
            "families": families,
        },
        "server": {
            "host": host,
            "port": port,
            "wildcard_bind": wildcard_bind,
            "editable": False,
        },
        "workspace": config.workspace.model_dump(),
        "provider_accounts": {
            "accounts": [
                account.model_dump()
                for account in config.provider_accounts.accounts
            ],
        },
        "ui": config.ui.model_dump(),
        "server_prefs": {
            **config.server_prefs.model_dump(),
            "effective_bind_host": bound_host,
            "tls_available": False,
            "restart_required": True,
        },
    }
