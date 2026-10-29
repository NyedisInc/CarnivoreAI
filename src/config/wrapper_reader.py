
from __future__ import annotations

from src.config import settings
from src.core.agent_wrappers import AgentWrapper
from src.core.sessions import wrapper_source


def configured_wrappers() -> list[AgentWrapper]:
    return wrapper_source.configured_wrappers(settings_provider=lambda: settings)
