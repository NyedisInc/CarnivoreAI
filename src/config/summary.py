
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
    """Build the payload for ``GET /api/v1/config/settings``.

      ``effective_bind_host`` is the address in force, read from the
      STARTUP RECORD and passed in as ``bound_host``. It used to be the
      CONFIGURED host, which made the screen render "in force: the server
      is on 0.0.0.0" for an install whose only socket was on loopback.
      None is a third state the client renders as such, never substituted
      with the preference.
    Inputs: config (AuthConfig) - the loaded document; host (str | None)
      and port (int) - the configured bind; families (list[dict]) - from :func:`family_summaries`;
      bound_host (str | None) - what actually bound at startup.
    Output: dict with ``agents``, ``server``,
      ``workspace``, ``provider_accounts``, ``ui``
      and ``server_prefs``.
    Example: settings_summary(cfg, host="0.0.0.0", port=8000, ...)
    """
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
