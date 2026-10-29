from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_alf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_alf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import automation_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.automations import models as m  # noqa: E402
from src.core.automations import session_tree, targets  # noqa: E402
from src.core.automations.store import AutomationStore  # noqa: E402
from src.core.automations.store_schema import storage_for  # noqa: E402
from src.core.crosstalk import directory  # noqa: E402
from src.core.mcp import federated, session_target, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
LIVE_UUID, ASLEEP_UUID = "uuid-live-0001", "uuid-asleep-0002"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "automations" / "session_tree_cases.json"


async def _runner(ctx, automation, run):
    return m.RunOutcome()


def _info(name: str, session_id: str) -> SimpleNamespace:
    return SimpleNamespace(tmux_session=name, host_key="local", session_row_id=7,
                           session=SimpleNamespace(id=session_id, working_dir="/w", agent_type="claude"))


class Manager:

    _registry = SimpleNamespace(find_hidden_id=lambda _target: None)

    async def list_session_infos(self):
        return [_info("cloude_live", "ses_live")]


class View:

    gate_waited = False

    def __init__(self, app):
        self.app = app


@pytest.fixture
def world(tmp_path, monkeypatch):
    from src.config import settings

    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, _runner)
    store = AutomationStore(storage_for(tmp_path), notify=lambda _t: None)
    app = FastAPI()
    app.include_router(automation_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.state.automation_store = store
    app.state.session_manager = Manager()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)

    async def no_peers(force=False):
        return []

    monkeypatch.setattr(federated, "peer_infos", no_peers)
    monkeypatch.setattr(directory, "_asleep_rows", lambda: [{"session_uuid": ASLEEP_UUID, "tmux_name": "cloude_asleep", "project_id": 2}])
    monkeypatch.setattr(session_target, "_session_uuid_of_row", lambda row_id: LIVE_UUID)
    inputs = {"projects": [{"id": 1, "name": "api"}, {"id": 2, "name": "site"}],
              "sessions": [{"session_uuid": LIVE_UUID, "tmux_name": "cloude_live", "name": None, "project_id": 1, "archived_at": None},
                           {"session_uuid": ASLEEP_UUID, "tmux_name": "cloude_asleep", "name": None, "project_id": 2, "archived_at": None}]}
    monkeypatch.setattr(session_tree, "read_inputs", lambda: inputs)
    msg = lambda uuid: {"kind": "session_message", "session_uuid": uuid, "text": "hi", "if_gone": "fail"}  # noqa: E731
    store.create(name="to live", cron="0 7 * * 1", target=msg(LIVE_UUID), project_id=2)
    store.create(name="to asleep", cron="0 7 * * 1", target=msg(ASLEEP_UUID))
    store.create(name="api scrooge", cron="0 7 * * 1", target={"kind": "recipe", "recipe": "scrooge"}, project_id=1)
    store.create(name="api off", cron="0 7 * * 1", target={"kind": "recipe", "recipe": "scrooge"}, project_id=1, enabled=False)
    store.create(name="site scrooge", cron="0 7 * * 1", target={"kind": "recipe", "recipe": "scrooge"}, project_id=2)
    store.create(name="loose", cron="0 7 * * 1", target={"kind": "recipe", "recipe": "scrooge"})
    return SimpleNamespace(app=app, client=TestClient(app), store=store)


def _names(body):
    return sorted(a["name"] for a in body["automations"])


def _mcp(world, args):
    result = asyncio.run(tools.call_tool(View(world.app), PANE, "automations_list", args))
    return result, (json.loads(result["content"][0]["text"]) if not result.get("isError") else result["content"][0]["text"])


def test_each_filter_narrows_and_mcp_returns_the_routes_body(world):
    everything = world.client.get("/automations").json()
    assert len(everything["automations"]) == 6
    assert _names(world.client.get("/automations", params={"project_id": 1}).json()) == ["api off", "api scrooge"]
    assert _names(world.client.get("/automations", params={"enabled": "false"}).json()) == ["api off"]
    assert _names(world.client.get("/automations", params={"target_kind": "session_message"}).json()) == ["to asleep", "to live"]
    for name in (LIVE_UUID, "ses_live", "cloude_live"):
        assert _names(world.client.get("/automations", params={"session": name}).json()) == ["api off", "api scrooge", "to live"], name
    for name in (ASLEEP_UUID, "cloude_asleep"):
        assert _names(world.client.get("/automations", params={"session": name}).json()) == ["site scrooge", "to asleep", "to live"], name
    both = world.client.get("/automations", params={"session": "cloude_live", "enabled": "true", "target_kind": "recipe"}).json()
    assert _names(both) == ["api scrooge"]
    assert world.client.get("/automations", params={"target_kind": "nope"}).status_code == 422
    assert world.client.get("/automations", params={"group_by": "project"}).status_code == 422

    result, via_mcp = _mcp(world, {"session": "cloude_live", "enabled": True, "target_kind": "recipe"})
    assert not result.get("isError") and _names(via_mcp) == ["api scrooge"]
    assert via_mcp == both
    assert _mcp(world, {"project_id": 1})[1] == world.client.get("/automations", params={"project_id": 1}).json()
    assert _mcp(world, {})[1] == everything
    assert _mcp(world, {"enabled": "yes"})[0].get("isError") and _mcp(world, {"bogus": 1})[0].get("isError")


def test_an_unknown_session_is_a_clear_error_on_the_route_and_over_mcp(world):
    got = world.client.get("/automations", params={"session": "cloude_nothing"})
    assert got.status_code == 404 and got.json()["detail"]["code"] == "session_not_found"
    assert "cloude_nothing" in got.json()["detail"]["message"]
    result, text = _mcp(world, {"session": "cloude_nothing"})
    assert result.get("isError") and "cloude_nothing" in text


def test_group_by_session_files_projects_sessions_and_unassigned(world):
    body = world.client.get("/automations", params={"group_by": "session"}).json()
    tree = {n["key"]: n for n in body["tree"]}
    assert body["group_by"] == "session" and list(tree) == ["project:1", "project:2", "unassigned"]
    live = tree["project:1"]["children"][0]
    assert live["key"] == f"session:{LIVE_UUID}" and [a["name"] for a in live["automations"]] == ["to live"]
    assert [a["name"] for a in tree["project:1"]["automations"]] == ["api off", "api scrooge"]
    assert [c["session_uuid"] for c in tree["project:2"]["children"]] == [ASLEEP_UUID]
    assert [a["name"] for a in tree["project:2"]["children"][0]["automations"]] == ["to asleep"]
    assert [a["name"] for a in tree["project:2"]["automations"]] == ["site scrooge"]
    assert [a["name"] for a in tree["unassigned"]["automations"]] == ["loose"] and tree["unassigned"]["children"] == []
    assert all(a["last_run"] is None for n in body["tree"] for a in n["automations"])
    assert tree["project:1"]["count"] == 3
    narrowed = world.client.get("/automations", params={"group_by": "session", "project_id": 1}).json()["tree"]
    assert [n["key"] for n in narrowed] == ["project:1"] and narrowed[0]["count"] == 2
    via_mcp = _mcp(world, {"group_by": "session", "session": "cloude_asleep"})[1]
    assert [n["key"] for n in via_mcp["tree"]] == ["project:1", "project:2"]
    assert _mcp(world, {"group_by": "session"})[1] == body


def test_the_server_tree_matches_the_sessions_tab_on_the_shared_fixture():
    cases = json.loads(FIXTURE.read_text())["cases"]
    assert len(cases) > 1 and any(c["expected"] for c in cases)

    def compact(n):
        return {"key": n["key"], "kind": n["kind"], "label": n["label"], "project_id": n["project_id"], "session_uuid": n["session_uuid"],
                "automations": [a["name"] for a in n["automations"]], "children": [compact(c) for c in n["children"]],
                "next_fire_at": n["next_fire_at"], "last_run": n["last_run"]["run_id"] if n["last_run"] else None, "count": n["count"]}

    for case in cases:
        tree = session_tree.build_tree(case["projects"], case["sessions"], case["automations"])
        assert [compact(n) for n in tree] == case["expected"], case["name"]
