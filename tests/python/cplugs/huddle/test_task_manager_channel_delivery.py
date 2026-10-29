
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import one_shot_routes
from src.config.mcp import McpConfig
from src.core.mcp import channel
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

SEND = "/api/v1/cplugs/huddle/lists/12/send"


@pytest.fixture
def channels(app, monkeypatch):
    cfg = McpConfig(channels=True)
    monkeypatch.setattr(channel, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    registry = channel.ChannelRegistry()
    monkeypatch.setattr(channel, "REGISTRY", registry)
    app.state.services = SimpleNamespace(registry=SimpleNamespace(
        get_session=lambda sid: SimpleNamespace(tmux_session=f"cloude_{sid}")))
    state = SimpleNamespace(cfg=cfg, registry=registry, gated=[], refuse=None)

    async def check(request, session_id, text):
        state.gated.append(session_id)
        if state.refuse is not None:
            raise state.refuse
        clean = SimpleNamespace(text=text, byte_length=len(text.encode()), stripped_count=0)
        return one_shot_routes.GatedBody(SimpleNamespace(tmux_session=f"cloude_{session_id}"), None, clean,
                                         None, "node", "idle", None)

    monkeypatch.setattr(one_shot_routes, "check_through_gates", check)
    return state


def untold(client) -> bool:
    return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == "12")["untold"]


def queued(stream) -> list:
    out = []
    while not stream.queue.empty():
        out.append(stream.queue.get_nowait())
    return out


def test_a_pane_with_a_live_channel_gets_a_channel_event_and_the_tell_is_recorded(client, app, pasted, channels):
    stream = channels.registry.open("cloude_ses_old", "ses_old")
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "by channel"})
    note(app, "ses_old", "12", 100.0)
    told = client.post(SEND, json={}).json()
    assert (told["target"], told["delivered_via"], told["submitted"]) == ("ses_old", "channel", True)
    assert pasted == [] and channels.gated == ["ses_old"]
    (event,) = queued(stream)
    assert event["method"] == "notifications/claude/channel"
    assert event["params"]["content"] == told["text"] and "(list 12, since 0)" in told["text"]
    assert event["params"]["meta"] == {"source_kind": "huddle", "list": "12"}
    assert untold(client) is False


def test_no_channel_stream_falls_back_to_the_paste_and_records_the_same_way(client, app, pasted, channels):
    channels.registry.open("cloude_ses_new", "ses_new")
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "by paste"})
    note(app, "ses_old", "12", 100.0)
    told = client.post(SEND, json={}).json()
    assert (told["target"], told["delivered_via"]) == ("ses_old", "paste")
    assert [s for s, _t in pasted] == ["ses_old"] and channels.gated == []
    assert untold(client) is False


def test_setting_off_pastes_even_with_a_stream_open(client, app, pasted, channels):
    stream = channels.registry.open("cloude_ses_old", "ses_old")
    channels.cfg.channels = False
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "off"})
    note(app, "ses_old", "12", 100.0)
    assert client.post(SEND, json={}).json()["delivered_via"] == "paste"
    assert [s for s, _t in pasted] == ["ses_old"] and queued(stream) == []


def test_a_busy_pane_holds_a_channel_tell_and_records_nothing(client, app, pasted, channels):
    stream = channels.registry.open("cloude_ses_old", "ses_old")
    channels.refuse = HTTPException(status_code=409, detail={"code": "pane_dialog_open", "message": "a dialog is open"})
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "while a dialog is open"})
    note(app, "ses_old", "12", 100.0)
    body = client.post(SEND, json={}).json()
    assert (body["status"], body["code"]) == ("held", "pane_dialog_open")
    assert queued(stream) == [] and pasted == []
    assert untold(client) is True
    client.delete("/api/v1/cplugs/huddle/held/12")


def test_a_push_the_registry_declines_after_the_gate_pastes_the_gated_body(client, app, pasted, channels, monkeypatch):
    channels.registry.open("cloude_ses_old", "ses_old")
    monkeypatch.setattr(channels.registry, "push", lambda *a: False)
    sent = []

    async def paste_gated(gated, session_id):
        sent.append((session_id, gated.clean.text))
        return SimpleNamespace(pasted_bytes=gated.clean.byte_length, submitted=True)

    monkeypatch.setattr(one_shot_routes, "paste_gated", paste_gated)
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "declined"})
    note(app, "ses_old", "12", 100.0)
    told = client.post(SEND, json={}).json()
    assert told["delivered_via"] == "paste" and [s for s, _t in sent] == ["ses_old"]
    assert pasted == [] and channels.gated == ["ses_old"]
    assert untold(client) is False
