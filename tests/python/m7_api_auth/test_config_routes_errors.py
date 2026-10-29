
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import config_routes

LEAK = "/Users/someone/private/config.json line 3"


def test_common_commands_failure_does_not_echo_the_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(path):
        raise ValueError(LEAK)

    monkeypatch.setattr(config_routes.slash_favorites, "payload", broken)
    with pytest.raises(HTTPException) as err:
        asyncio.run(config_routes.get_common_commands())
    assert err.value.status_code == 500
    assert "someone" not in str(err.value.detail)


def test_slash_commands_failure_does_not_echo_the_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args, **kwargs):
        raise OSError(LEAK)

    monkeypatch.setattr(config_routes, "build_command_groups", broken)
    monkeypatch.setattr(config_routes, "user_scope_roots", lambda request: (None, None))
    with pytest.raises(HTTPException) as err:
        asyncio.run(config_routes.get_slash_commands(SimpleNamespace(), project_path=None))
    assert err.value.status_code == 500
    assert "someone" not in str(err.value.detail)
