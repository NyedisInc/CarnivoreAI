
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

from src.core.mcp import pending, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.models.session_move import SessionMoveResponse  # noqa: E402

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
READ_ONLY = AgentCaller("ses_a", "cloude_a", "ses_a", scope="read")
UUID_B = "b0b0b0b0-0000-4000-8000-000000000001"


def _info(name: str, host: str = "local") -> SimpleNamespace:
    return SimpleNamespace(activity_status="idle", status_source="none", subagents_running=None, background_open=None,
                           tmux_session=name, host_key=host, session_row_id=1, host_label="far",
                           session=SimpleNamespace(id=f"ses_{name.removeprefix('cloude_')}", tmux_created_epoch=7))


class View:

    gate_waited = False

    def __init__(self) -> None:
        self.infos = [_info("cloude_a"), _info("cloude_b")]
        known = {i.session.id for i in self.infos}
        registry = SimpleNamespace(resolve_session_id=lambda sid: sid if sid in known else None, subscribers={})
        manager = SimpleNamespace(list_session_infos=self._list)
        self.app = SimpleNamespace(state=SimpleNamespace(session_manager=manager, services=SimpleNamespace(registry=registry)))

    async def _list(self) -> list:
        return self.infos

    async def list_infos(self) -> list:
        return self.infos

    async def list_peer_infos(self) -> list:
        return []


def _plan(live: bool = True, ok: bool = True, files: int = 2, applied: bool = False) -> SessionMoveResponse:
    return SessionMoveResponse(
        session_uuid=UUID_B, tmux_name="cloude_b", destination="/proj/app", file_count=files, kills_live_pane=live,
        ok=ok, refusals=[] if ok else [{"code": "collision", "message": "the destination already has notes.md"}],
        applied=applied)


@pytest.fixture()
def world(monkeypatch):
    from src.api import session_move_routes

    calls: list = []
    state = {"plan": _plan()}

    async def route(session_uuid, body, request):
        calls.append((session_uuid, body.apply, body.confirm_restart_live))
        return state["plan"] if not body.apply else _plan(live=state["plan"].kills_live_pane, applied=True)

    async def no_pin(manager, target_id):
        return 7, "cloude_b"

    async def everyone(manager):
        return await manager.list_infos()

    monkeypatch.setattr(session_move_routes, "move_session_folder", route)
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    monkeypatch.setattr("src.core.mcp.write_tools.approval_runtime.pin", no_pin)
    monkeypatch.setattr("src.core.mcp.common._all_infos", everyone)
    monkeypatch.setattr("src.core.mcp.session_target.TargetResolver.uuid_of", _uuid_of)
    return View(), calls, state


async def _uuid_of(self, target) -> str:
    return UUID_B


def _call(view, args, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(view, caller, "session_folder_move", args))


def _approve() -> None:
    store = pending.get_store()
    assert len(store.list()) == 1
    asyncio.run(store.approve(store.list()[0]["id"]))


def test_a_refused_plan_answers_the_reason_and_never_asks_the_owner(world):
    view, calls, state = world
    state["plan"] = _plan(ok=False)
    answer = _call(view, {"target": "cloude_b", "project_id": 3})
    assert "notes.md" in str(answer) and pending.get_store().list() == []
    assert calls == [(UUID_B, False, False)]


def test_the_move_waits_then_confirms_the_live_restart_the_owner_was_asked_about(world):
    view, calls, _ = world
    assert "pending" in str(_call(view, {"target": "cloude_b", "project_id": 3}))
    assert [c[1] for c in calls] == [False]
    _approve()
    assert calls[-1] == (UUID_B, True, True)


def test_an_exited_pane_is_moved_without_the_live_confirmation(world):
    view, calls, state = world
    state["plan"] = _plan(live=False)
    _call(view, {"target": "cloude_b", "new_folder": "/proj/app"})
    _approve()
    assert calls[-1] == (UUID_B, True, False)


def test_a_pane_that_went_live_after_the_ask_is_not_killed(world):
    view, calls, state = world
    state["plan"] = _plan(live=False)
    _call(view, {"target": "cloude_b", "project_id": 3})
    state["plan"] = _plan(live=True)
    _approve()
    assert all(c[1] is False for c in calls), calls


def test_it_refuses_its_own_session_a_paired_session_and_bad_destinations(world):
    view, calls, _ = world
    assert "own session" in str(_call(view, {"target": "cloude_a", "project_id": 3}))
    view.infos.append(_info("far_one", host="peer-1"))
    view.infos[-1].session.id = "remote:peer-1:x"
    assert "paired computer" in str(_call(view, {"target": "remote:peer-1:x", "project_id": 3}))
    assert "exactly one" in str(_call(view, {"target": "cloude_b"}))
    assert "exactly one" in str(_call(view, {"target": "cloude_b", "project_id": 3, "new_folder": "/x"}))
    assert calls == []


def test_a_read_token_never_sees_the_tool(world):
    view, calls, _ = world
    assert "session_folder_move" not in [t["name"] for t in tools.tool_definitions(READ_ONLY)]
    assert "session_folder_move" in tools.WRITE_TOOLS and calls == []
    assert "not allowed" in str(_call(view, {"target": "cloude_b", "project_id": 3}, READ_ONLY)).lower() or calls == []
