import asyncio
from types import SimpleNamespace
from typing import Optional

import pytest

from src.core.session_manager import SessionManager

LOGIN_NAME = "carnivore_login_codex"


def _manager_with_backend(name: str) -> tuple[SessionManager, list[Optional[str]]]:
    mgr = object.__new__(SessionManager)
    mgr._registry = SimpleNamespace(backends={"ses_login": SimpleNamespace(tmux_session=name)})
    destroyed: list[Optional[str]] = []

    async def fake_destroy(session_id: Optional[str] = None) -> bool:
        destroyed.append(session_id)
        return True

    mgr.destroy_session = fake_destroy  # type: ignore[method-assign]
    return mgr, destroyed


def test_external_close_of_an_active_backend_is_refused_and_tears_nothing_down() -> None:
    mgr, destroyed = _manager_with_backend(LOGIN_NAME)
    with pytest.raises(ValueError, match="DELETE /sessions"):
        asyncio.run(mgr.destroy_external_session(LOGIN_NAME))
    assert destroyed == []
