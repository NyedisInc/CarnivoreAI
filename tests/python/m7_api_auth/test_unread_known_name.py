
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import List

import pytest
from fastapi import HTTPException

from src.api import session_theme_routes as routes
from src.models import SetUnreadRequest


class FakeManager:

    def __init__(self) -> None:
        self.writes: List[tuple[str, bool]] = []

    def active_tmux_names(self) -> set[str]:
        return {"carnivore_live"}

    def list_attachable_sessions(self) -> list:
        return []

    def set_manual_unread(self, name: str, unread: bool) -> None:
        self.writes.append((name, unread))


def _request(manager: FakeManager) -> SimpleNamespace:
    services = SimpleNamespace(owned_tmux=SimpleNamespace(names={"carnivore_owned"}))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=manager, services=services)))


def _mark(manager: FakeManager, name: str, unread: bool = True):
    return asyncio.run(routes.set_session_unread(_request(manager), name, SetUnreadRequest(unread=unread)))


def test_an_unknown_name_is_a_404_and_writes_nothing() -> None:
    manager = FakeManager()
    with pytest.raises(HTTPException) as err:
        _mark(manager, "../../not-a-session")
    assert err.value.status_code == 404
    assert manager.writes == []


@pytest.mark.parametrize("name", ["carnivore_live", "carnivore_owned", "adopted:carnivore_live"])
def test_a_known_name_is_marked(name: str) -> None:
    manager = FakeManager()
    assert _mark(manager, name).success is True
    assert manager.writes == [(name.removeprefix("adopted:"), True)]


def test_marking_read_stays_open_for_a_name_that_is_gone() -> None:
    manager = FakeManager()
    assert _mark(manager, "carnivore_gone", unread=False).success is True
    assert manager.writes == [("carnivore_gone", False)]
