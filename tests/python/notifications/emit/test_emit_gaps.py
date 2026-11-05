
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from src.core.notifications import contracts
from tests.python.notifications.emit.rig import SESSION, EmitRig

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def rig(tmp_path, monkeypatch):
    wired = EmitRig(tmp_path, monkeypatch)
    await wired.start()
    yield wired
    await wired.stop()


async def test_the_toast_api_route_is_an_agent_message_card_and_reaches_a_destination(rig: EmitRig) -> None:
    from src.api.session_toast_routes import create_session_toast
    from src.models import CreateToastRequest

    request = SimpleNamespace(state=SimpleNamespace(), app=SimpleNamespace(state=SimpleNamespace(session_manager=rig.manager)))
    toast = await create_session_toast(request, SESSION, CreateToastRequest(kind="Notification", title="nightly build is green"))
    await rig.settle()

    assert toast.notify_type == "agent.message"
    assert [json.loads(p)["toast"]["notify_type"] for p in rig.session_frames] == ["agent.message"]
    assert [e.type_id for e in rig.handled] == ["agent.message"]
    assert len(rig.delivered("agent.message")) == 1


async def test_the_retired_session_posted_id_routes_as_agent_message(rig: EmitRig) -> None:
    contracts.emit(contracts.NotifyEvent(type_id="session.posted", kind="Notification", title="t", ts=0.0, instance_key="old"))
    await rig.settle()

    assert [e.type_id for e in rig.sender.calls[0][:1]] == ["agent.message"]
