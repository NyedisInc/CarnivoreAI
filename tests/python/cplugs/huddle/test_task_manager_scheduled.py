
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.cplugs.huddle import service
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import CALLER, Env, call, iso  # noqa: F401

ROUTE = "/api/v1/cplugs/huddle/scheduled"
DAILY = {"freq": "daily", "time": "09:00"}


def test_the_route_and_the_tool_share_one_filtered_and_ordered_view(app, client, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore", "13": "site"})
    env = Env(app, monkeypatch)
    store = env.store
    later = store.add("12", "later one-shot", actor="joe", title="later", fire_at=iso(7200))["id"]
    soon = store.add("13", "soon one-shot", actor="joe", fire_at=iso(600))["id"]
    daily = store.add("12", "daily sweep", actor="joe", title="sweep", fire_at=iso(1800), repeat=DAILY)["id"]
    parked = store.add("13", "parked sweep", actor="joe", title="parked", fire_at=iso(60), repeat=DAILY)["id"]
    store.update(parked, actor="joe", paused=True)
    store.add("all", "no schedule", actor="joe")

    body = client.get(ROUTE).json()
    assert [(s["item"], s["list"]) for s in body["schedules"]] == [(soon, "13"), (daily, "12"), (later, "12"), (parked, "13")]
    first = body["schedules"][0]
    assert first["list_name"] == "site" and first["title"] == "soon one-shot" and first["paused"] is False
    assert first["pings"]["project"] == "site" and first["pings"]["session"] is None
    assert datetime.fromisoformat(first["next_fire"]).utcoffset() is not None
    assert body["schedules"][1]["repeat"] == DAILY and body["schedules"][3]["paused"] is True
    assert body["schedules"][2]["pings"]["session"] in {"ses_new", "ses_codex"}
    assert body["schedules"][2]["pings"]["session_key"] == body["schedules"][2]["pings"]["session"]
    assert first["pings"]["session_key"] is None
    assert [(g["list"], [i["id"] for i in g["items"]]) for g in body["groups"]] == [("12", [daily, later]), ("13", [soon, parked])]

    assert [s["item"] for s in client.get(ROUTE, params={"list": "12"}).json()["schedules"]] == [daily, later]
    assert [s["item"] for s in client.get(ROUTE, params={"paused": "true"}).json()["schedules"]] == [parked]
    assert [s["item"] for s in client.get(ROUTE, params={"paused": "false"}).json()["schedules"]] == [soon, daily, later]
    assert client.get(ROUTE, params={"list": "bad"}).status_code == 400

    ok, tool = call(app, "task_manager_schedules_list", {})
    assert ok and tool["schedules"] == body["schedules"] and tool["total"] == 4
    ok, only = call(app, "task_manager_schedules_list", {"list": "13", "paused": True})
    assert ok and [s["item"] for s in only["schedules"]] == [parked]
    ok, text = call(app, "task_manager_schedules_list", {"paused": "yes"})
    assert not ok and "paused" in text


def test_the_route_needs_auth(app):
    with TestClient(app) as anonymous:
        assert anonymous.get(ROUTE).status_code in (401, 403)
