
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from src.api import session_toast_routes as routes
from src.models import CreateToastRequest


class FakeManager:

    def __init__(self) -> None:
        self.asked: List[str] = []

    def record_toast(self, *, session_id: str, **kwargs: Any) -> Any:
        self.asked.append(session_id)
        if session_id != "ses_local":
            raise ValueError("unknown session")
        return SimpleNamespace(session_id=session_id, id="t1", model_dump_json=lambda: "{}")


def _request(manager: FakeManager, peer: bool) -> Any:
    registry = SimpleNamespace(sessions={"ses_local": object()}, get_backend=lambda sid: object(),
                               registered_ids_for_tmux_name=lambda name: ["ses_local"] if name == "carnivore_x" else [])
    state = SimpleNamespace(peer_grant=object() if peer else None)
    app = SimpleNamespace(state=SimpleNamespace(session_manager=manager, services=SimpleNamespace(registry=registry, toasts=None)))
    return SimpleNamespace(app=app, state=state)


@pytest.fixture(autouse=True)
def _no_broadcast(monkeypatch: pytest.MonkeyPatch) -> None:
    async def silent(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(routes.connection_manager, "broadcast_to_session", silent)


def test_a_peer_name_is_mapped_to_the_local_session_id() -> None:
    manager = FakeManager()
    body = CreateToastRequest(kind="Stop", title="t")
    asyncio.run(routes.create_session_toast(_request(manager, peer=True), "carnivore_x", body))
    assert manager.asked == ["ses_local"]


def test_a_peer_name_that_is_not_a_local_session_is_a_404() -> None:
    manager = FakeManager()
    body = CreateToastRequest(kind="Stop", title="t")
    with pytest.raises(HTTPException) as err:
        asyncio.run(routes.create_session_toast(_request(manager, peer=True), "someone_elses", body))
    assert err.value.status_code == 404
    assert "someone_elses" not in manager.asked, "the raw peer-supplied name must never reach the toast inbox"


def test_the_owners_own_id_passes_through() -> None:
    manager = FakeManager()
    body = CreateToastRequest(kind="Stop", title="t")
    asyncio.run(routes.create_session_toast(_request(manager, peer=False), "ses_local", body))
    assert manager.asked == ["ses_local"]
