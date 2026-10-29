
from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.mcp import beast_mode, pending, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

ASLEEP_UUID = "2c1d6510-966a-4ef2-8a91-bb3f0dc3b2dd"
PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
READ_ONLY = AgentCaller("ses_a", "cloude_a", "ses_a", scope="read")


def _info(name: str, host: str = "local") -> SimpleNamespace:
    return SimpleNamespace(activity_status="idle", status_source="none", subagents_running=None, background_open=None,
                           tmux_session=name, host_key=host, session_row_id=1, host_label="far",
                           session=SimpleNamespace(id=f"ses_{name.removeprefix('cloude_')}", tmux_created_epoch=7))


class View:

    gate_waited = False

    def __init__(self):
        infos = [_info("cloude_a"), _info("cloude_b")]
        known = {i.session.id for i in infos}
        registry = SimpleNamespace(resolve_session_id=lambda sid: sid if sid in known else None, subscribers={})
        manager = SimpleNamespace(list_session_infos=self._list)
        self.infos = infos
        self.app = SimpleNamespace(state=SimpleNamespace(session_manager=manager, services=SimpleNamespace(registry=registry)))

    async def _list(self):
        return self.infos

    async def list_infos(self):
        return self.infos

    async def list_peer_infos(self):
        return []


@pytest.fixture()
def world(monkeypatch):
    from src.api import session_attach_routes, session_crud_routes

    calls: list = []

    async def destroy(request, session_id=None, confirm_name=None):
        calls.append(("destroy_session", session_id))

    async def external(request, name, confirm_name=None):
        calls.append(("destroy_external_session", name))

    monkeypatch.setattr(session_crud_routes, "destroy_session", destroy)
    monkeypatch.setattr(session_attach_routes, "destroy_external_session", external)
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)

    async def no_pin(manager, target_id):
        return 7, "cloude_b"

    async def everyone(manager):
        return await manager.list_infos()

    monkeypatch.setattr("src.core.mcp.write_tools.approval_runtime.pin", no_pin)
    monkeypatch.setattr("src.core.mcp.common._all_infos", everyone)

    from src.api import session_records_routes
    from src.core.crosstalk import directory
    from src.core.mcp import drawer_pins

    async def record_delete(request, session_uuid, confirm_name=None):
        calls.append(("delete_session_record", session_uuid))

    async def write_pinned(request, change):
        pins["now"] = change(pins["now"])
        calls.append(("unpin", tuple(pins["now"])))
        return pins["now"]

    pins = {"now": [ASLEEP_UUID, "other-uuid"]}
    asleep = {"rows": [{"id": 41, "session_uuid": ASLEEP_UUID, "tmux_name": "carnivore_switch"}]}
    monkeypatch.setattr(session_records_routes, "delete_session_record", record_delete)
    monkeypatch.setattr(drawer_pins, "write_pinned", write_pinned)
    monkeypatch.setattr(directory, "_asleep_rows", lambda: list(asleep["rows"]))
    view = View()
    view.asleep = asleep
    view.pins = pins
    return view, calls


def _call(view, name, args, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(view, caller, name, args))


def _approve_only() -> None:
    store = pending.get_store()
    assert len(store.list()) == 1
    asyncio.run(store.approve(store.list()[0]["id"]))


def test_delete_waits_then_runs_through_the_route(world):
    view, calls = world
    answer = _call(view, "session_delete", {"target": "cloude_b"})
    assert "pending" in str(answer) and calls == []
    _approve_only()
    assert calls == [("destroy_session", "ses_b")]


def test_unregistered_session_goes_through_the_external_route(world):
    view, calls = world
    view.app.state.services.registry.resolve_session_id = lambda sid: None
    _call(view, "session_delete", {"target": "cloude_b"})
    _approve_only()
    assert calls == [("destroy_external_session", "cloude_b")]


def test_always_waits_even_with_beast_mode_on(world, monkeypatch):
    view, calls = world
    arm_beast(monkeypatch, lambda: True)
    assert beast_mode.approval_skip("session_delete") is False
    assert beast_mode.approval_skip("session_stop") is True
    assert "pending" in str(_call(view, "session_delete", {"target": "cloude_b"}))
    assert calls == [] and len(pending.get_store().list()) == 1


def test_refuses_its_own_session(world):
    view, calls = world
    answer = _call(view, "session_delete", {"target": "cloude_a"})
    assert answer.get("isError") and "own session" in str(answer)
    assert calls == [] and pending.get_store().list() == []


def test_unknown_target_and_extra_args(world):
    view, calls = world
    assert _call(view, "session_delete", {"target": "nope"}).get("isError")
    assert _call(view, "session_delete", {"target": "cloude_b", "confirm_name": "x"}).get("isError")
    assert calls == []


def test_refuses_a_paired_computers_session(world):
    view, calls = world
    view.infos.append(_info("far_one", host="peer-1"))
    view.infos[-1].session.id = "remote:peer-1:x"
    answer = _call(view, "session_delete", {"target": "remote:peer-1:x"})
    assert answer.get("isError") and calls == []


def test_read_only_token_cannot_see_or_call_it(world):
    view, calls = world
    assert "session_delete" not in {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    assert "session_delete" in {t["name"] for t in tools.tool_definitions(PANE)}
    assert _call(view, "session_delete", {"target": "cloude_b"}, READ_ONLY).get("isError")
    assert calls == []


@pytest.mark.parametrize("target", [ASLEEP_UUID, "carnivore_switch"])
def test_asleep_delete_by_uuid_and_name_waits_then_deletes_and_unpins(world, target):
    view, calls = world
    answer = _call(view, "session_delete", {"target": target})
    assert "pending" in str(answer) and calls == []
    item = pending.get_store().list()[0]
    assert "asleep" in str(item).lower()
    _approve_only()
    assert calls == [("delete_session_record", ASLEEP_UUID), ("unpin", ("other-uuid",))]
    assert view.pins["now"] == ["other-uuid"]


def test_asleep_delete_always_waits_even_with_beast_mode_on(world, monkeypatch):
    view, calls = world
    arm_beast(monkeypatch, lambda: True)
    assert "pending" in str(_call(view, "session_delete", {"target": ASLEEP_UUID}))
    assert calls == [] and len(pending.get_store().list()) == 1


def test_asleep_record_that_woke_before_approval_is_not_deleted(world):
    view, calls = world
    _call(view, "session_delete", {"target": "carnivore_switch"})
    view.asleep["rows"][0] = {"id": 99, "session_uuid": ASLEEP_UUID, "tmux_name": "carnivore_switch"}
    _approve_only()
    assert calls == []


def test_unknown_asleep_target_fails_and_files_nothing(world):
    view, calls = world
    answer = _call(view, "session_delete", {"target": "ses_deadbeef"})
    assert answer.get("isError") and calls == [] and pending.get_store().list() == []


def test_a_name_shared_by_two_asleep_rows_is_refused(world):
    view, calls = world
    view.asleep["rows"].append({"id": 42, "session_uuid": "u2", "tmux_name": "carnivore_switch"})
    answer = _call(view, "session_delete", {"target": "carnivore_switch"})
    assert answer.get("isError") and "session_uuid" in str(answer) and calls == []
