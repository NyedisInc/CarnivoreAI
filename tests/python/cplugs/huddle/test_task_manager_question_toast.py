
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cplugs.host import runtime
from src.api.auth import require_auth
from src.cplugs.huddle import question_toasts, routes as huddle_routes
from src.cplugs.huddle.store import TaskManagerStore
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.sessions.toast_inbox import ToastInbox
from src.models import Toast
from tests.python.cplugs.owner import turn_on

CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")


class _Manager:

    def __init__(self, inbox: ToastInbox) -> None:
        self.inbox = inbox
        self.app = None
        self.gate_waited = True
        self._notification_policy_store = None
        own = SimpleNamespace(tmux_session=None, session=SimpleNamespace(id="ses_1"), project_id=12, host_key="local")

        async def infos():
            return [own]

        self.list_session_infos = infos

    def notification_policy_stamp(self, session_id: str):
        return None

    def record_toast(self, session_id: str, kind: str, title: str, body=None, *, notify_type=None) -> Toast:
        toast, _ = self.inbox.store(session_id, kind=kind, title=title, body=body, color=None,
                                    session_label=None, session_name=None, notify_type=notify_type)
        return toast


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    question_toasts.forget_all()
    pushes: list = []
    monkeypatch.setattr("src.core.sessions.toast_inbox.resource_push.notify", pushes.append)
    inbox = ToastInbox()
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    app.state.services = SimpleNamespace(toasts=inbox)
    manager = _Manager(inbox)
    manager.app = app
    app.state.session_manager = manager
    store = TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)
    yield SimpleNamespace(app=app, manager=manager, inbox=inbox, store=store, pushes=pushes)
    question_toasts.forget_all()


def ask(world, text: str = "which one?") -> dict:
    item = world.store.add("all", "decide", actor="joe")
    result = asyncio.run(tools.call_tool(world.manager, CALLER, "task_manager_ask", {"item": item["id"], "text": text, "lean": False}))
    body = json.loads(result["content"][0]["text"])
    assert body["notified"] is True
    return {"item": item, "toast_id": world.inbox.get("ses_1", unacked_only=True)[0].id}


def unacked(world) -> list:
    return world.inbox.get("ses_1", unacked_only=True)


def owner_post(world, path: str, **kwargs):
    with TestClient(world.app) as client:
        return client.post(f"/api/v1/cplugs/huddle{path}", **kwargs)


def test_an_ask_raises_one_toast_and_it_stays_if_he_never_acts(world):
    asked = ask(world)
    assert [t.id for t in unacked(world)] == [asked["toast_id"]]
    asyncio.run(tools.call_tool(world.manager, CALLER, "task_manager_reply", {"item": asked["item"]["id"], "text": "fyi"}))
    assert [t.id for t in unacked(world)] == [asked["toast_id"]]


@pytest.mark.parametrize("act", ["reply", "open", "mark_read", "tick"])
def test_each_owner_act_clears_the_toast_and_pushes_the_toasts_topic(world, act):
    asked = ask(world)
    pushes_before = len(world.pushes)
    item_id = asked["item"]["id"]
    if act == "reply":
        r = owner_post(world, f"/items/{item_id}/messages", json={"text": "the first"})
    elif act in ("open", "mark_read"):
        r = owner_post(world, f"/items/{item_id}/seen")
    else:
        with TestClient(world.app) as client:
            r = client.patch(f"/api/v1/cplugs/huddle/items/{item_id}", json={"approved": True})
    assert r.status_code == 200, r.text
    assert unacked(world) == []
    assert "toasts" in world.pushes[pushes_before:]


def test_the_owner_marking_it_answered_clears_the_toast(world):
    asked = ask(world)
    assert owner_post(world, f"/items/{asked['item']['id']}/answered").status_code == 200
    assert unacked(world) == []


def test_huddle_mark_answered_by_claude_clears_the_toast(world):
    asked = ask(world)
    result = asyncio.run(tools.call_tool(world.manager, CALLER, "task_manager_answered_set", {"item": asked["item"]["id"]}))
    assert not result.get("isError")
    assert unacked(world) == []


def test_acting_on_one_item_leaves_another_items_toast(world):
    first, second = ask(world), ask(world, "and this?")
    owner_post(world, f"/items/{first['item']['id']}/seen")
    assert [t.id for t in unacked(world)] == [second["toast_id"]]


def test_a_second_act_is_a_quiet_no_op(world):
    asked = ask(world)
    owner_post(world, f"/items/{asked['item']['id']}/seen")
    pushes = len(world.pushes)
    owner_post(world, f"/items/{asked['item']['id']}/seen")
    assert len(world.pushes) == pushes
