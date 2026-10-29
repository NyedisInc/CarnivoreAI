
from __future__ import annotations

from typing import Any, Callable, Protocol

import structlog

from src.core.agent_wrappers import AgentWrapper

logger = structlog.get_logger(__name__)

WRAPPER_READ_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError)


class AuthConfigSource(Protocol):

    def load_auth_config(self) -> Any:
        ...


SettingsProvider = Callable[[], AuthConfigSource]
WrappersReader = Callable[[], list[AgentWrapper]]


def configured_wrappers(*, settings_provider: SettingsProvider) -> list[AgentWrapper]:
    try:
        return list(settings_provider().load_auth_config().agents.wrappers or [])
    except WRAPPER_READ_ERRORS as exc:
        logger.warning("configured_wrappers_unavailable", error=str(exc))
        return []
