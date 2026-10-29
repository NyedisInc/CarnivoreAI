
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import one_shot_routes
from src.cplugs.huddle import service
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

URL = "/api/v1/cplugs/huddle/send"


@pytest.fixture(autouse=True)
def two_projects(app, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore", "99": "other", "81": "Trader"})


def untold(client, key: str) -> bool:
    return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == key)["untold"]


def test_each_list_goes_to_its_own_session_and_a_list_with_none_asks(client, app, pasted):
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "in carnivore"})
    client.post("/api/v1/cplugs/huddle/lists/99/items", json={"text": "in other"})
    client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "shared"})
    note(app, "ses_old", "12", 100.0)
    body = client.post(URL, json={"lists": ["12", "99"]}).json()["results"]
    assert [(r["list"], r["status"], r.get("target")) for r in body] == [("12", "sent", "ses_old"), ("99", "sent", "ses_other")]
    assert [s for s, _t in pasted] == ["ses_old", "ses_other"]
    assert "(list 12, since 0)" in pasted[0][1] and "(list 99, since 0)" in pasted[1][1]
    assert untold(client, "12") is False and untold(client, "99") is False


def test_a_list_with_no_default_is_not_pasted_and_answers_its_candidates_then_a_choice_sends_it(client, pasted):
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "three sessions, no caller"})
    first = client.post(URL, json={"lists": ["12", "99"]}).json()["results"]
    assert first[0]["status"] == "no_session" and [s["id"] for s in first[0]["sessions"]] == ["ses_codex", "ses_new", "ses_old"]
    assert first[1]["status"] == "sent" and [s for s, _t in pasted] == ["ses_other"]
    assert untold(client, "12") is True
    stray = client.post(URL, json={"lists": ["12"], "targets": {"12": "ses_other"}}).json()["results"]
    assert stray[0]["status"] == "no_session" and len(pasted) == 1
    chosen = client.post(URL, json={"lists": ["12"], "targets": {"12": "ses_new"}}).json()["results"]
    assert (chosen[0]["status"], chosen[0]["target"], chosen[0]["reason"]) == ("sent", "ses_new", "chosen")
    assert untold(client, "12") is False


def test_the_shared_list_is_told_as_itself_not_as_every_list(client, app, pasted):
    client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "shared"})
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "project"})
    note(app, "ses_new", "all", 100.0)
    body = client.post(URL, json={"lists": ["all"]}).json()["results"]
    assert body[0]["status"] == "sent"
    assert "the shared swarm list changed" in pasted[0][1] and "(list all, since 0)" in pasted[0][1]
    assert "list 12" not in pasted[0][1]
    assert untold(client, "all") is False and untold(client, "12") is True


def test_a_refused_paste_is_reported_for_that_list_and_the_others_still_go(client, app, monkeypatch):
    sent = []

    async def paste(request, session_id, text):
        if session_id == "ses_old":
            raise HTTPException(status_code=409, detail={"code": "paste_dialog_open", "detail": "a dialog is open"})
        sent.append(session_id)
        return SimpleNamespace(pasted_bytes=len(text), submitted=True)

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", paste)
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    body = client.post(URL, json={"lists": ["12", "99"]}).json()["results"]
    assert (body[0]["status"], body[0]["code"], body[0]["label"], body[0]["reason"]) == (
        "refused", "paste_dialog_open", "ses_old", "a dialog is open")
    assert body[1]["status"] == "sent" and sent == ["ses_other"]
    assert untold(client, "12") is True


def test_an_empty_or_unknown_list_is_refused(client, pasted):
    assert client.post(URL, json={"lists": []}).status_code == 400
    assert client.post(URL, json={"lists": ["77"]}).status_code == 404
    assert pasted == []


def waiting(client, key: str) -> int:
    return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == key)["waiting_to_send"]


@pytest.mark.parametrize("url", [URL, "/api/v1/cplugs/huddle/lists/12/send"])
def test_a_tick_then_a_tell_sends_it_the_count_drops_at_once_with_no_read(client, app, pasted, url):
    item = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "tick me"}).json()
    note(app, "ses_old", "12", 100.0)
    client.post(URL, json={"lists": ["12"]})
    assert waiting(client, "12") == 0
    client.patch(f"/api/v1/cplugs/huddle/items/{item['id']}", json={"approved": True})
    assert waiting(client, "12") == 1
    told = client.post(url, json={"lists": ["12"]} if url == URL else {})
    assert told.status_code == 200
    assert waiting(client, "12") == 0
    assert client.get("/api/v1/cplugs/huddle/lists/12").json()["items"][0]["status"] == "done"
    client.patch(f"/api/v1/cplugs/huddle/items/{item['id']}", json={"approved": False})
    assert waiting(client, "12") == 1


def test_a_project_with_no_session_offers_every_session_to_pick_and_a_pick_sends_it(client, pasted):
    client.post("/api/v1/cplugs/huddle/lists/81/items", json={"text": "trader test item"})
    first = client.post(URL, json={"lists": ["81"]}).json()["results"][0]
    assert first["status"] == "no_session" and not pasted
    assert first["sessions"] and all(s["elsewhere"] for s in first["sessions"])
    assert {s["id"] for s in first["sessions"]} >= {"ses_old", "ses_other"}
    assert any("(" in s["label"] for s in first["sessions"])
    choice = client.get("/api/v1/cplugs/huddle/lists/81/sessions").json()
    assert choice["default"] is None and choice["sessions"]
    sent = client.post(URL, json={"lists": ["81"], "targets": {"81": "ses_other"}}).json()["results"][0]
    assert (sent["status"], sent["target"]) == ("sent", "ses_other") and pasted[-1][0] == "ses_other"
    assert untold(client, "81") is False


def test_a_project_with_no_session_is_never_delivered_silently_even_to_its_last_huddle_caller(client, app, pasted):
    note(app, "ses_other", "81", 500.0)
    client.post("/api/v1/cplugs/huddle/lists/81/items", json={"text": "trader item"})
    choice = client.get("/api/v1/cplugs/huddle/lists/81/sessions").json()
    assert (choice["default"], choice["reason"]) == (None, "pick")
    many = client.post(URL, json={"lists": ["81"]}).json()["results"][0]
    assert many["status"] == "no_session"
    one = client.post("/api/v1/cplugs/huddle/lists/81/send", json={})
    assert one.status_code == 409 and one.json()["detail"]["code"] == "task_manager_pick_session"
    assert not pasted
    assert untold(client, "81") is True


def test_a_list_holding_only_deleted_items_is_not_untold_but_a_live_change_is(client):
    item = client.post("/api/v1/cplugs/huddle/lists/81/items", json={"text": "test item"}).json()["id"]
    assert untold(client, "81") is True
    assert client.delete(f"/api/v1/cplugs/huddle/items/{item}").status_code == 200
    assert untold(client, "81") is False
    client.post("/api/v1/cplugs/huddle/lists/81/items", json={"text": "real"})
    assert untold(client, "81") is True


def test_a_tell_to_a_project_whose_agent_is_asleep_wakes_it_then_sends(client, app, pasted, monkeypatch):
    from src.cplugs.huddle import send_wake
    from tests.python.cplugs.huddle.test_task_manager_routes import row
    client.post("/api/v1/cplugs/huddle/lists/81/items", json={"text": "wake me"})
    rows = [row("ses_other", 99)]
    woke = []

    async def wake_project(ctx, key):
        woke.append(key)
        rows.append(row("ses_trader", 81))
        return "ses_trader"

    async def infos():
        return list(rows)

    app.state.session_manager.list_session_infos = infos
    monkeypatch.setattr(send_wake, "wake_project", wake_project)
    out = client.post(URL, json={"lists": ["81"]}).json()["results"][0]
    assert woke == ["81"] and out["status"] == "sent" and out["target"] == "ses_trader"
    assert [s for s, _t in pasted] == ["ses_trader"] and untold(client, "81") is False


def test_a_wake_that_fails_leaves_the_list_untold_and_says_so(client, app, pasted, monkeypatch):
    from src.cplugs.huddle import send_wake
    client.post("/api/v1/cplugs/huddle/lists/81/items", json={"text": "stays untold"})

    async def wake_project(ctx, key):
        raise send_wake.WakeFailed("never reached its prompt")

    monkeypatch.setattr(send_wake, "wake_project", wake_project)
    out = client.post(URL, json={"lists": ["81"]}).json()["results"][0]
    assert (out["status"], out["code"]) == ("refused", send_wake.WAKE_FAILED)
    assert pasted == [] and untold(client, "81") is True


def test_needs_wake_only_for_a_project_list_with_no_session_of_its_own():
    from src.cplugs.huddle.send_wake import needs_wake
    assert needs_wake("6", []) and needs_wake("6", [{"elsewhere": True}])
    assert not needs_wake("6", [{"elsewhere": False}]) and not needs_wake("all", []) and not needs_wake("agent:3", [])
