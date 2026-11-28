
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

from src.core.mcp import session_target, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.core.mcp.common import ToolError  # noqa: E402

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
ASLEEP = "aaaaaaaa-1111-4111-8111-111111111111"
TWIN_1 = "bbbbbbbb-2222-4222-8222-222222222222"
TWIN_2 = "cccccccc-3333-4333-8333-333333333333"
ORPHAN = "12d67d84-9428-4105-90d0-12b01f2d8670"


def _info(name: str) -> SimpleNamespace:
    return SimpleNamespace(claude_title=None, tmux_session=name, host_key="local", session_row_id=1, label=None, agent_type="claude",
                           project_name="p", activity_status="idle", unread=False, status_source="pane",
                           startup_gate="ready", subagents_state=None, subagents_running=None, background_open=None,
                           background_processes=None, task_lead=None, do_not_disturb=None,
                           session=SimpleNamespace(id=f"ses_{name}", working_dir="/w", agent_type="claude", pty_pid=1,
                                                   last_activity=None, tmux_created_epoch=1))


class View:

    gate_waited = False

    def __init__(self):
        self.app = SimpleNamespace(state=SimpleNamespace())

    async def list_session_infos(self):
        return [_info("cloude_live")]

    async def list_peer_infos(self):
        return []


@pytest.fixture()
def view(monkeypatch):
    from src.core.crosstalk import directory
    from src.core.mcp import pin_tools

    rows = [
        {"id": 1, "session_uuid": ASLEEP, "tmux_name": "cloude_sleepy", "title": "sleepy", "project_name": "p"},
        {"id": 2, "session_uuid": TWIN_1, "tmux_name": "cloude_twin"},
        {"id": 3, "session_uuid": TWIN_2, "tmux_name": "cloude_twin"},
    ]
    monkeypatch.setattr(directory, "_asleep_rows", lambda: list(rows))

    async def pinned(request):
        return [ASLEEP, ORPHAN]

    monkeypatch.setattr(pin_tools, "pinned_session_uuids", pinned)
    monkeypatch.setattr(pin_tools, "_names_of", lambda uuids: {ORPHAN: "carnivore_switch", ASLEEP: "cloude_sleepy"})
    return View()


def _resolve(view, target, reach):
    return asyncio.run(session_target.resolve_target(view, {"target": target}, reach=reach, tool="t"))


def test_live_resolves_first_and_costs_no_stored_read(view, monkeypatch):
    from src.core.crosstalk import directory

    monkeypatch.setattr(directory, "_asleep_rows", lambda: pytest.fail("a live hit must not read the asleep rows"))
    found = _resolve(view, "cloude_live", session_target.PINNED)
    assert found.kind == "live" and found.info.session.id == "ses_cloude_live"


@pytest.mark.parametrize("target", [ASLEEP, "cloude_sleepy"])
def test_asleep_resolves_by_uuid_and_by_tmux_name(view, target):
    found = _resolve(view, target, session_target.STORED)
    assert found.kind == "asleep" and found.session_uuid == ASLEEP and found.tmux_name == "cloude_sleepy"


def test_a_tmux_name_two_asleep_rows_share_is_refused(view):
    with pytest.raises(ToolError, match="use a session_uuid"):
        _resolve(view, "cloude_twin", session_target.STORED)
    assert _resolve(view, TWIN_2, session_target.STORED).session_uuid == TWIN_2


def test_a_live_only_tool_is_told_the_session_is_asleep(view):
    with pytest.raises(ToolError, match="asleep.*session_wake"):
        _resolve(view, "cloude_sleepy", session_target.LIVE)
    with pytest.raises(ToolError, match="no live session matches"):
        _resolve(view, "nobody", session_target.LIVE)


@pytest.mark.parametrize("target", [ORPHAN, "carnivore_switch"])
def test_an_orphan_pin_resolves_only_for_the_pin_reach(view, target):
    found = _resolve(view, target, session_target.PINNED)
    assert found.kind == "orphan_pin" and found.session_uuid == ORPHAN
    with pytest.raises(ToolError, match="no live or asleep session"):
        _resolve(view, target, session_target.STORED)


def test_sessions_list_includes_asleep_only_when_asked(view):
    plain = json.loads(asyncio.run(tools.call_tool(view, PANE, "sessions_list", {}))["content"][0]["text"])
    assert [r["id"] for r in plain["sessions"]] == ["ses_cloude_live"]
    both = json.loads(asyncio.run(tools.call_tool(view, PANE, "sessions_list", {"include_asleep": True}))["content"][0]["text"])
    asleep = [r for r in both["sessions"] if r.get("asleep")]
    assert {r["id"] for r in asleep} == {ASLEEP, TWIN_1, TWIN_2}
    assert all(r["activity_status"] == "asleep" and r["session_uuid"] == r["id"] for r in asleep)
    assert asyncio.run(tools.call_tool(view, PANE, "sessions_list", {"include_asleep": "yes"}))["isError"] is True


def test_sessions_list_shows_the_roles_only_when_they_were_measured(view):
    live = lambda: json.loads(asyncio.run(tools.call_tool(view, PANE, "sessions_list", {}))["content"][0]["text"])["sessions"][0]  # noqa: E731
    assert "task_lead" not in live() and "do_not_disturb" not in live()
    original = view.list_session_infos

    async def measured():
        rows = await original()
        rows[0].task_lead, rows[0].do_not_disturb = True, False
        return rows

    view.list_session_infos = measured
    assert (live()["task_lead"], live()["do_not_disturb"]) == (True, False)


def test_session_status_answers_an_asleep_session(view):
    answer = json.loads(asyncio.run(tools.call_tool(view, PANE, "session_status", {"target": "cloude_sleepy"}))["content"][0]["text"])
    assert answer["asleep"] is True and answer["session_uuid"] == ASLEEP and answer["label"] == "sleepy"


def test_a_live_only_tool_answers_asleep_as_a_typed_error(view):
    answer = asyncio.run(tools.call_tool(view, PANE, "session_read_output", {"target": ASLEEP}))
    assert answer["isError"] is True and "session_wake" in answer["content"][0]["text"]



STOPPED_UUID = "dddddddd-4444-4444-8444-444444444444"
CLOSED_UUID = "eeeeeeee-5555-4555-8555-555555555555"


@pytest.fixture()
def stored_view(view, monkeypatch):
    from src.core.crosstalk import directory

    stopped = {"id": 4, "session_uuid": STOPPED_UUID, "tmux_name": "cloude_gone", "legacy_session_id": "ses_8a095b40"}
    closed = {"id": 5, "session_uuid": CLOSED_UUID, "tmux_name": "cloude_closed", "legacy_session_id": "ses_c10sed01",
              "lifecycle_source": "tmux_missing"}
    monkeypatch.setattr(directory, "_stopped_rows", lambda: [stopped])
    monkeypatch.setattr(directory, "_closed_rows", lambda: [closed])
    return view


def test_a_stopped_row_resolves_by_its_ses_id(stored_view):
    got = _resolve(stored_view, "ses_8a095b40", session_target.RECORD)
    assert got.session_uuid == STOPPED_UUID


def test_a_closed_row_resolves_by_its_ses_id(stored_view):
    got = _resolve(stored_view, "ses_c10sed01", session_target.CLOSED)
    assert (got.kind, got.session_uuid) == (session_target.KIND_CLOSED, CLOSED_UUID)


def test_a_closed_row_is_never_matched_by_name_or_by_a_guessed_id(stored_view):
    for target in ("cloude_closed", "ses_c10sed0", "ses_cloude_closed", "adopted:cloude_closed"):
        with pytest.raises(ToolError, match="no closed session"):
            _resolve(stored_view, target, session_target.CLOSED)


def test_an_asleep_row_resolves_by_its_ses_id_and_a_name_is_not_an_id(view, monkeypatch):
    from src.core.crosstalk import directory

    row = {"id": 6, "session_uuid": ASLEEP, "tmux_name": "cloude_sleepy", "legacy_session_id": "ses_5133p001"}
    monkeypatch.setattr(directory, "_asleep_rows", lambda: [row])
    assert _resolve(view, "ses_5133p001", session_target.STORED).session_uuid == ASLEEP
    with pytest.raises(ToolError):
        _resolve(view, "ses_cloude_sleepy", session_target.STORED)
