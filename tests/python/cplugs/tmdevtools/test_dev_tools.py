
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import developer_mode
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.host import runtime
from src.cplugs.huddle import devtools_port, groups, service as task_manager_service
from src.cplugs.huddle.store import TaskManagerStore
from src.cplugs.sdk import ports
from src.cplugs.tmdevtools import commands, routes
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/tmdevtools"
PANE = AgentCaller("ses_1", "cloude_a", "ses_1")
FOLD_TOOL, LIST_TOOL, SCROLL_TOOL = "task_manager_dev_fold_set", "task_manager_dev_tasks_list", "task_manager_dev_scroll_set"


class Env:

    def __init__(self, tmp: Path, monkeypatch: Any, on: bool = True) -> None:
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/api/v1")
        monkeypatch.setattr(developer_mode, "is_on", lambda: True)
        (tmp / "state").mkdir()
        self.host = runtime.install(self.app, tmp / "state")
        self.published: List[str] = []
        self.host.publish = self.published.append
        turn_on(self.host, "huddle")
        if on:
            turn_on(self.host, "tmdevtools")
        monkeypatch.setattr(task_manager_service, "project_names", lambda ctx: {"12": "carnivore", "13": "blog"})
        self.ctx = self.host.context("huddle", infos=self._infos, background=True)
        self.store = TaskManagerStore(self.host.storage("huddle"), notify=lambda key: None)
        devtools_port.register(self.ctx)

    @staticmethod
    async def _infos() -> list:
        return [SimpleNamespace(tmux_session=None, label="Agent One", session=SimpleNamespace(id="ses_1"), project_id=12, host_key="local")]

    @property
    def manager(self) -> Any:
        return SimpleNamespace(app=self.app, gate_waited=True, list_session_infos=self._infos)

    def call(self, name: str, args: Dict[str, Any]) -> Any:
        result = asyncio.run(tools.call_tool(self.manager, PANE, name, args))
        text = result["content"][0]["text"]
        return (False, text) if result.get("isError") else (True, json.loads(text))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: Any):
    made = Env(tmp_path, monkeypatch)
    yield made
    devtools_port.unregister()
    commands.reset()


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


def seed(env: Env) -> Dict[str, int]:
    store = env.store
    q = store.add("12", "which db", actor="claude")["id"]
    o = store.add("12", "build the bar", actor="claude")["id"]
    d = store.add("12", "old thing", actor="claude")["id"]
    b = store.add("13", "post draft", actor="claude")["id"]
    return {"q": q, "o": o, "d": d, "b": b}


def test_ships_off_and_the_manifest_asks_for_the_huddle() -> None:
    d = runtime.find("tmdevtools")
    assert d.manifest.default_enabled is False and "huddle" in d.manifest.requires
    assert sorted(d.tools) == [FOLD_TOOL, SCROLL_TOOL, LIST_TOOL]


def test_off_means_no_routes_and_no_tools(tmp_path: Path, monkeypatch: Any) -> None:
    off = Env(tmp_path, monkeypatch, on=False)
    off.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    try:
        with TestClient(off.app) as client:
            for method, path in (("get", "/commands"), ("get", "/tasks"), ("post", "/scroll-top"), ("post", "/fold")):
                refused = getattr(client, method)(BASE + path, **({"json": {}} if method == "post" else {}))
                assert refused.status_code == 409 and refused.json()["detail"]["code"] == "cplug_disabled", path
        ok, text = off.call(LIST_TOOL, {})
        assert not ok
    finally:
        devtools_port.unregister()
        commands.reset()


def test_scroll_top_pushes_one_command_a_browser_reads_once(env: Env, client: TestClient) -> None:
    sent = client.post(BASE + "/scroll-top", json={}).json()
    assert sent["sent"] is True and sent["list"] is None
    assert env.published[-1] == "cplug.tmdevtools.command"
    first = client.get(BASE + "/commands").json()
    assert [c["kind"] for c in first["commands"]] == ["scroll_top"] and first["latest"] == sent["seq"]
    assert client.get(BASE + f"/commands?after={sent['seq']}").json()["commands"] == []


def test_a_fresh_browser_is_not_served_an_old_command(env: Env, client: TestClient, monkeypatch: Any) -> None:
    client.post(BASE + "/scroll-top", json={})
    monkeypatch.setattr(commands.time, "monotonic", lambda: 10_000_000.0)
    assert client.get(BASE + "/commands").json()["commands"] == []
    assert client.get(BASE + "/commands?after=0").json()["commands"][0]["kind"] == "scroll_top"


def test_scroll_top_resolves_a_project_and_refuses_an_unknown_one(env: Env, client: TestClient) -> None:
    seed(env)
    assert client.post(BASE + "/scroll-top", json={"list": "Carnivore"}).json()["list"] == "12"
    missing = client.post(BASE + "/scroll-top", json={"list": "nope"})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "tmdevtools_not_found"


def test_fold_resolves_names_to_ids_and_pushes(env: Env, client: TestClient) -> None:
    ids = seed(env)
    group = groups.GroupWriter(env.store).create("12", "ui", actor="claude")
    ok, answer = env.call(FOLD_TOOL, {"action": "fold", "group": "UI", "project": "carnivore"})
    assert ok and answer["groups"] == [group["id"]] and answer["action"] == "fold"
    ok, answer = env.call(FOLD_TOOL, {"action": "unfold", "project": "blog"})
    assert ok and answer["project"] == "blog"
    ok, answer = env.call(FOLD_TOOL, {"action": "close", "items": [ids["o"]]})
    assert ok and answer["items"] == [ids["o"]]
    sent = client.get(BASE + "/commands?after=0").json()["commands"]
    assert [c["action"] for c in sent] == ["fold", "unfold", "close"]
    assert sent[1]["project"] == "13" and sent[0]["groups"] == [group["id"]] and sent[0]["project"] is None


def test_fold_refusals(env: Env) -> None:
    ids = seed(env)
    for args in ({"action": "spin"}, {"action": "fold"}, {"action": "close", "group": "x"}, {"action": "fold", "group": "ghost"},
                 {"action": "fold", "items": [99999]}, {"action": "fold", "project": "nope"}, {"action": "fold", "items": ["a"]}):
        ok, text = env.call(FOLD_TOOL, args)
        assert not ok and "refused" in text, args
    ok, answer = env.call(FOLD_TOOL, {"action": "close"})
    assert ok and answer["items"] == [] and ids


def test_list_filters_combine_and_hide_ticked_tasks(env: Env, client: TestClient) -> None:
    ids = seed(env)
    group = groups.GroupWriter(env.store).create("12", "ui", actor="claude")
    groups.GroupWriter(env.store).set_group(ids["o"], group["id"], actor="claude")
    env.store.update(ids["d"], actor="joe", approve=True)
    ok, every = env.call(LIST_TOOL, {})
    assert ok and {r["id"] for r in every["rows"]} == {ids["q"], ids["o"], ids["b"]}
    row = next(r for r in every["rows"] if r["id"] == ids["b"])
    assert row["project"] == "blog" and row["title"] == "post draft" and set(row) >= {"id", "title", "status", "project", "group", "tag"}
    ok, mine = env.call(LIST_TOOL, {"project": "carnivore"})
    assert {r["id"] for r in mine["rows"]} == {ids["q"], ids["o"]}
    ok, done = env.call(LIST_TOOL, {"status": "done"})
    assert [r["id"] for r in done["rows"]] == [ids["d"]]
    ok, none = env.call(LIST_TOOL, {"project": "blog", "status": "done"})
    assert ok and none["rows"] == [] and none["total"] == 0
    ok, grouped = env.call(LIST_TOOL, {"group": "UI"})
    assert ok and [(r["id"], r["group"]) for r in grouped["rows"]] == [(ids["o"], "ui")]
    ok, tagged = env.call(LIST_TOOL, {"tag": "any"})
    assert ok and tagged["rows"] == []
    ok, untagged = env.call(LIST_TOOL, {"tag": "none", "project": "carnivore"})
    assert {r["id"] for r in untagged["rows"]} == {ids["q"], ids["o"]}
    assert client.get(BASE + "/tasks", params={"project": "blog"}).json()["rows"][0]["id"] == ids["b"]
    assert client.get(BASE + "/tasks", params={"project": "zzz"}).status_code == 404


def test_list_projects_counts_by_status(env: Env) -> None:
    ids = seed(env)
    env.store.update(ids["d"], actor="joe", approve=True)
    ok, answer = env.call(LIST_TOOL, {"view": "projects"})
    by_name = {p["project"]: p for p in answer["projects"]}
    assert ok and by_name["carnivore"]["open_tasks"] == 2 and by_name["carnivore"]["counts"]["done"] == 1 and by_name["blog"]["open_tasks"] == 1


def test_the_tools_say_so_when_the_huddle_is_off(env: Env) -> None:
    devtools_port.unregister()
    assert ports.get(devtools_port.NAME) is None
    ok, text = env.call(LIST_TOOL, {})
    assert not ok and "tmdevtools_no_task_manager" in text
