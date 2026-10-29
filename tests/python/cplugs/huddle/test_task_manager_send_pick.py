
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

BASE = "/api/v1/cplugs/huddle/lists"


def put(client, target, key: str = "12"):
    return client.put(f"{BASE}/{key}/send-target", json={"target": target})


def test_the_route_needs_auth(app):
    with TestClient(app) as anonymous:
        assert anonymous.put(f"{BASE}/12/send-target", json={"target": None}).status_code in (401, 403)


def test_a_pick_becomes_the_default_and_the_tell_goes_there(client, app, pasted):
    note(app, "ses_old", "12", 100.0)
    assert client.get(f"{BASE}/12/sessions").json()["default"] == "ses_old"
    out = put(client, "ses_codex").json()
    assert (out["default"], out["reason"]) == ("ses_codex", "picked")
    assert client.get(f"{BASE}/12/sessions").json()["default"] == "ses_codex"
    told = client.post(f"{BASE}/12/send", json={}).json()
    assert (told["target"], told["reason"]) == ("ses_codex", "picked") and pasted[0][0] == "ses_codex"
    many = client.post("/api/v1/cplugs/huddle/send", json={"lists": ["12"]}).json()["results"][0]
    assert many["status"] == "sent" and many["target"] == "ses_codex"


def test_null_goes_back_to_the_derived_default(client, app):
    note(app, "ses_old", "12", 100.0)
    put(client, "ses_new")
    out = put(client, None).json()
    assert (out["default"], out["reason"]) == ("ses_old", "last_task_manager_caller")


def test_a_session_that_is_not_a_candidate_is_refused_and_nothing_is_stored(client):
    assert put(client, "ses_other").status_code == 404
    assert client.get(f"{BASE}/12/sessions").json()["reason"] == "pick"


def test_the_pick_is_per_list_and_a_pick_with_no_candidate_left_is_ignored(client, app):
    put(client, "ses_old")
    assert client.get(f"{BASE}/all/sessions").json()["reason"] != "picked"
    app.state.session_manager.list_session_infos = _without("ses_old", app)
    assert client.get(f"{BASE}/12/sessions").json()["reason"] != "picked"


def test_a_pick_notifies_the_list_topic(client, app, monkeypatch):
    from src.cplugs.huddle import service
    seen = []
    monkeypatch.setattr(service, "store", _recording(service.store, seen))
    put(client, "ses_new")
    assert seen == ["12"]


def _without(session_id: str, app):
    before = app.state.session_manager.list_session_infos

    async def infos():
        return [r for r in await before() if r.session.id != session_id]
    return infos


def _recording(real, seen):
    def make(ctx):
        store = real(ctx)
        original = store._notify
        store._notify = lambda key: (seen.append(key), original(key))[1]
        return store
    return make
