
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx
import pytest

from src.core.argent import cards_sync, notices, work_items
from src.core.swarm.cards import notices as card_notices, port as card_port
from src.plugins.huddle import lane
from tests.argent.test_argent_work_items import env, fixture  # noqa: F401

APP = object()


class FakePort:

    def __init__(self) -> None:
        self.rows: Dict[int, Dict[str, Any]] = {}
        self.moves: List[Dict[str, Any]] = []

    async def cards(self, **_: Any) -> List[Dict[str, Any]]:
        return list(self.rows.values())

    async def card(self, card_id: int) -> Optional[Dict[str, Any]]:
        return self.rows.get(card_id)

    async def act(self, op: str, card_id: Optional[int], args: Dict[str, Any], by: str) -> Dict[str, Any]:
        if op == "create":
            kind, _, ref = args["origin"].partition(":")
            card = {"id": len(self.rows) + 1, "title": args["title"], "parent": args["parent"], "list_key": args["list_key"], "level": args["level"],
                    "origin": {"kind": kind, "ref": ref}, "column": "todo", "state": "open", "holder": None, "last_holder": None}
            self.rows[card["id"]] = card
            return {"card": card, "effects": [], "data": {}}
        card = self.rows[int(card_id or 0)]
        if op == "owner_note":
            return {"card": card, "effects": [], "data": {}}
        card["column"] = args["column"] if op == "set_column" else ("in_progress" if args.get("queued") else "todo")
        self.moves.append({"op": op, "to": card["column"]})
        return {"card": card, "effects": [], "data": {}}


@pytest.fixture
def world(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:  # noqa: F811
    port, wins, notes = FakePort(), [], []
    card_port.register(port)
    monkeypatch.setattr(notices, "tracker_wins", lambda *a: wins.append(a))
    monkeypatch.setattr(card_notices, "note", lambda state, before, after, *, owner_note="": notes.append(owner_note))
    state: Dict[str, Any] = {"status": "in_progress", "healthy": True, "calls": [], "projects": {"fixtureproject": 7}}

    async def projects() -> Dict[str, Optional[int]]:
        return state["projects"]

    monkeypatch.setattr(cards_sync, "_projects", projects)

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"].append(request)
        if request.url.path == "/v1/my/trackers":
            page = fixture("trackers.json")
            page["items"][0]["healthy"] = state["healthy"]
            return httpx.Response(200, json=page)
        page = fixture("work_items_page.json")
        page["items"][2]["status"] = state["status"]
        if request.url.params.get("kind") == "story":
            page["items"] = page["items"][2:]
        return httpx.Response(200, json=page)

    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(handler), None
    asyncio.run(work_items.pull_once())
    state["calls"].clear()
    yield {"port": port, "wins": wins, "notes": notes, "state": state}
    card_port.register(None)


def sync() -> Dict[str, int]:
    return asyncio.run(cards_sync.sync_once(APP))


def test_one_card_per_story_under_its_feature_and_a_second_pass_or_a_delete_makes_no_more(world: Dict[str, Any]) -> None:
    assert sync() == {"created": 1, "moved": 0, "unmapped": 0, "skipped": 0}
    cards = {c["origin"]["ref"]: c for c in world["port"].rows.values()}
    assert set(cards) == {"argent:wi_feat1", "github:wi_story1"} and cards["github:wi_story1"]["parent"] == cards["argent:wi_feat1"]["id"]
    assert (cards["argent:wi_feat1"]["level"], cards["github:wi_story1"]["level"], cards["github:wi_story1"]["list_key"]) == ("feature", "task", "7")
    assert any(c.url.params.get("scope") == "mine" for c in world["state"]["calls"])
    assert sync()["created"] == 0 and len(world["port"].rows) == 2, "a second pass must not make a second card"
    world["port"].rows.clear()
    assert sync()["created"] == 0 and not world["port"].rows, "a card the owner deleted stays deleted"


def test_a_story_in_no_matching_project_gets_no_card(world: Dict[str, Any]) -> None:
    world["state"]["projects"] = {"someotherproject": 3}
    assert sync()["unmapped"] == 1 and not world["port"].rows
    world["state"]["projects"] = {"fixtureproject": None}
    assert sync()["unmapped"] == 1 and not world["port"].rows


@pytest.mark.parametrize(("status", "column", "expected"), [("backlog", "todo", "todo"), ("Won't Fix", "done", "done")])
def test_the_tracker_wins_mid_work(world: Dict[str, Any], status: str, column: str, expected: str) -> None:
    sync()
    story = next(c for c in world["port"].rows.values() if c["level"] == "task")
    story["column"] = "in_progress"
    world["state"]["status"] = status
    work_items._pull.client = None
    asyncio.run(work_items.pull_once())
    assert sync()["moved"] == 1 and story["column"] == expected
    assert [w[2] for w in world["wins"]] == ["backlogged" if status == "backlog" else "closed"]
    assert world["notes"] and "tracker" in world["notes"][0]
    assert sync()["moved"] == 0 and len(world["wins"]) == 1, "an already moved card is left alone"


def test_a_card_the_tracker_did_not_touch_or_an_unhealthy_tracker_keeps_the_card_in_the_work(world: Dict[str, Any]) -> None:
    sync()
    story = next(c for c in world["port"].rows.values() if c["level"] == "task")
    story["column"] = "in_progress"
    assert sync()["moved"] == 0 and story["column"] == "in_progress" and not world["wins"]
    world["state"].update(status="done", healthy=False)
    work_items._pull.client = None
    assert sync()["moved"] == 0 and story["column"] == "in_progress" and not world["wins"]
    world["state"]["healthy"] = True
    work_items._pull.client = None
    assert sync()["moved"] == 1 and story["column"] == "done"


def test_the_origin_kind_changes_no_existing_lane_and_off_means_nothing_runs(world: Dict[str, Any]) -> None:
    assert cards_sync.ORIGIN_KIND == lane.ARGENT_ORIGIN
    for origin, expected in {"owner": "task_manager", "": "task_manager", "session:k": "task_manager", "agent:7": "swarm", "spawn:3": "swarm",
                             "argent:github:wi_story1": "task_manager"}.items():
        assert lane.from_origin(origin) == expected, origin
    assert not cards_sync.is_running()
    cards_sync.bind(None)
    world["state"]["calls"].clear()
    assert asyncio.run(cards_sync.sync_once()) == {"created": 0, "moved": 0, "unmapped": 0, "skipped": 0} and not world["state"]["calls"]


def test_project_names_match_ignoring_case_spaces_dashes_and_dots(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.swarm import body

    async def rows(_: Any) -> List[Dict[str, Any]]:
        return [{"id": 7, "display_name": "Fixture-Project"}, {"id": 8, "display_name": "Other"}, {"id": 9, "display_name": "OTHER."}]

    monkeypatch.setattr(body, "run_db", rows)
    found = asyncio.run(cards_sync._projects())
    assert found == {"fixtureproject": 7, "other": None}
    with pytest.raises(AssertionError):
        assert "fixture project" in found
