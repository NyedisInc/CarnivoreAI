
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.mcp import beast_mode, pending, route_adapters, session_target, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

PANE = AgentCaller("ses_cloude_a", "cloude_a", "ses_cloude_a")
READ_ONLY = AgentCaller("ses_cloude_a", "cloude_a", "ses_cloude_a", scope="read")
EXTERNAL = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="laptop")
ASLEEP = "aaaaaaaa-1111-4111-8111-111111111111"
LIVE_UUID = "dddddddd-4444-4444-8444-444444444444"
SPECS = [s for m in tools._ROUTE_MODULES for s in getattr(m, "SPECS", ())]


def _info(name: str) -> SimpleNamespace:
    return SimpleNamespace(tmux_session=name, host_key="local", session_row_id=9, label=None, host_label="here",
                           session=SimpleNamespace(id=f"ses_{name}", working_dir="/w", tmux_created_epoch=1))


class View:

    gate_waited = False

    def __init__(self):
        self.app = SimpleNamespace(state=SimpleNamespace())

    async def list_session_infos(self):
        return [_info("cloude_a"), _info("cloude_b")]

    async def list_peer_infos(self):
        return []

    def fresh(self):
        return self


@pytest.fixture()
def world(monkeypatch):
    from src.core.crosstalk import directory

    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    arm_beast(monkeypatch, lambda: False)
    monkeypatch.setattr(directory, "_asleep_rows", lambda: [{"id": 5, "session_uuid": ASLEEP, "tmux_name": "cloude_nap"}])
    monkeypatch.setattr(session_target, "_session_uuid_of_row", lambda row_id: LIVE_UUID)
    calls: list = []
    for spec in SPECS:
        module, name = spec.route.split(":")

        async def recorder(*args, _route=spec.route, **kwargs):
            calls.append((_route, args, kwargs))
            return {"ok": True}

        monkeypatch.setattr(f"{module}.{name}", recorder)
    return calls


def _args(spec) -> dict:
    if not spec.reach:
        return dict(spec.example)
    return {"target": ASLEEP if spec.name == "session_wake" else "cloude_b", **spec.example}


def _call(name, args, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


@pytest.mark.parametrize("spec", SPECS, ids=[s.name for s in SPECS])
def test_every_adapter_calls_its_route(world, monkeypatch, spec):
    arm_beast(monkeypatch, lambda: True)
    answer = _call(spec.name, _args(spec))
    assert not answer.get("isError"), answer
    if spec.name in beast_mode.ALWAYS_WAITS:
        assert json.loads(answer["content"][0]["text"])["status"] == "pending" and world == []
        return
    routes = [c[0] for c in world]
    assert routes == [spec.route], routes
    if spec.reach:
        sent = json.dumps([world[0][1], world[0][2]], default=repr)
        assert any(v in sent for v in ("ses_cloude_b", "cloude_b", LIVE_UUID, ASLEEP)), sent


def test_bad_arguments_never_reach_a_route(world):
    for spec in SPECS:
        assert _call(spec.name, {**_args(spec), "surplus": 1})["isError"] is True
        if spec.required:
            assert _call(spec.name, {k: v for k, v in _args(spec).items() if k not in spec.required})["isError"] is True
    assert world == []


def test_a_read_token_sees_and_runs_only_the_reads(world):
    listed = {d["name"] for d in tools.tool_definitions(READ_ONLY)}
    for spec in SPECS:
        assert (spec.name in listed) == (spec.gate == route_adapters.READ), spec.name
    for name in ("session_interrupt", "session_dialog_answer", "project_delete", "beastmode_off"):
        assert name not in listed and _call(name, {"target": "cloude_b"}, READ_ONLY)["isError"] is True
    assert {"session_dialog_get", "dashboards_list", "preferences_get", "themes_list"} <= listed
    writes = [s for s in SPECS if s.gate != route_adapters.READ]
    for spec in writes:
        assert spec.name in tools.WRITE_TOOLS and _call(spec.name, _args(spec), READ_ONLY)["isError"] is True
    assert world == []


def test_an_arrange_write_runs_for_a_pane_and_waits_for_an_external_token(world):
    assert not _call("dashboard_rename", {"dashboard_id": "b1", "name": "ops"}).get("isError")
    assert len(world) == 1
    held = _call("dashboard_rename", {"dashboard_id": "b1", "name": "ops2"}, EXTERNAL)
    assert "pending" in str(held) and len(world) == 1


def test_an_act_write_waits_for_the_owner_then_runs_the_route(world):
    held = _call("project_create", {"name": "demo", "path": "/tmp/demo"})
    assert "pending" in str(held) and world == []
    store = pending.get_store()
    asyncio.run(store.approve(store.list()[0]["id"]))
    assert [c[0] for c in world] == ["src.api.projects_routes:create_project"]


def test_preferences_update_refuses_owner_only_fields(world):
    for field in ("theme_script_consent", "disabled_plugins", "desktop_terminal_app", "desktop_terminal_custom"):
        assert _call("preferences_update", {"changes": {field: {}}})["isError"] is True
    assert world == []


def test_item_settings_update_is_widgets_only(world):
    answer = _call("item_settings_update", {"kind": "plugin", "item_id": "huddle", "enabled": True})
    assert answer["isError"] is True and world == []


def test_wake_refuses_a_live_session(world, monkeypatch):
    arm_beast(monkeypatch, lambda: True)
    assert _call("session_wake", {"target": "cloude_b"})["isError"] is True and world == []


def test_custom_adapters_call_their_routes(world, monkeypatch):
    from src.api import beast_mode_routes, projects_routes, session_dialog_routes, session_interrupt_routes
    from src.core.mcp import project_tools
    from src.models.background_work import InterruptResponse
    from src.models.dialogs import DialogAnswerResponse, DialogResponse

    arm_beast(monkeypatch, lambda: True)
    seen: list = []

    async def interrupt(request, session_id, body):
        seen.append(("interrupt", session_id, body.confirm))
        return InterruptResponse.model_construct(sent=True)

    async def get_dialog(request, session_id):
        seen.append(("get_dialog", session_id))
        return DialogResponse(dialog={"kind": "permission", "fingerprint": "f" * 64, "options": ["Yes", "No"], "multi_select": False,
                                      "tabs": []})

    async def answer(request, session_id, body):
        seen.append(("answer", session_id, body.choice.option))
        return DialogAnswerResponse(kind="permission", fingerprint=body.fingerprint)

    async def delete(name, request):
        seen.append(("delete_project", name))
        return {"success": True}

    async def name_of(project_id, include_archived=False):
        return "demo"

    async def put(body, source):
        seen.append(("put_beast_mode", body.enabled))
        return {"enabled": False}

    monkeypatch.setattr(session_interrupt_routes, "interrupt_session", interrupt)
    monkeypatch.setattr(session_dialog_routes, "get_dialog", get_dialog)
    monkeypatch.setattr(session_dialog_routes, "answer_session_dialog", answer)
    monkeypatch.setattr(projects_routes, "delete_project", delete)
    monkeypatch.setattr(project_tools, "_current_name", name_of)
    monkeypatch.setattr(beast_mode_routes, "set_beast_mode", put)
    assert not _call("session_interrupt", {"target": "cloude_b"}).get("isError")
    assert not _call("session_dialog_get", {"target": "cloude_b"}).get("isError")
    assert not _call("session_dialog_answer", {"target": "cloude_b", "fingerprint": "f" * 64,
                                                "choice": {"option": "Yes"}}).get("isError")
    assert not _call("beastmode_off", {}).get("isError")
    assert "pending" in str(_call("project_delete", {"project": 3}))
    store = pending.get_store()
    asyncio.run(store.approve(store.list()[0]["id"]))
    assert seen == [("interrupt", "ses_cloude_b", True), ("get_dialog", "ses_cloude_b"),
                    ("get_dialog", "ses_cloude_b"), ("answer", "ses_cloude_b", "Yes"), ("put_beast_mode", False), ("delete_project", "demo")]


CLOSED_UUID = "cccccccc-3333-4333-8333-333333333333"


@pytest.mark.parametrize("tool", ["session_wake", "session_restart"])
def test_wake_of_a_tmux_missing_row_with_a_conversation_reaches_recreate(world, monkeypatch, tool):
    from src.core.crosstalk import directory

    row = {"id": 970, "session_uuid": CLOSED_UUID, "tmux_name": "carnivore_gone", "agent_type": "claude",
           "lifecycle": "stopped", "lifecycle_source": "tmux_missing", "claude_session_uuid": "conv-1"}
    monkeypatch.setattr(directory, "_closed_rows", lambda: [row])

    async def recorder(*args, **kwargs):
        world.append(("src.api.recreate_routes:recreate_session", args, kwargs))
        return {"status": "ok"}

    monkeypatch.setattr("src.api.recreate_routes.recreate_session", recorder)
    arm_beast(monkeypatch, lambda: True)
    world.clear()
    answer = _call(tool, {"target": CLOSED_UUID})
    assert not answer.get("isError"), answer
    assert [c[0] for c in world] == ["src.api.recreate_routes:recreate_session"]
    body = world[0][1][1]
    assert (body.session_uuid, body.agent_type) == (CLOSED_UUID, "claude")
    assert _call("session_wake", {"target": "carnivore_gone"})["isError"] is True


    class Empty(View):
        async def list_session_infos(self):
            return []

    def listing(args):
        out = asyncio.run(tools.call_tool(Empty(), PANE, "sessions_list", args))
        return json.loads(out["content"][0]["text"])["sessions"]

    assert [s["id"] for s in listing({"include_closed": True}) if s.get("closed")] == [CLOSED_UUID]
    assert listing({}) == []
