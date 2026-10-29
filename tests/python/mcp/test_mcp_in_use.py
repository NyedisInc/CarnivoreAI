
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.mcp import beast_mode, in_use, pending, tools, write_tools  # noqa: E402
from src.core.mcp.approvals import display  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
NOW = datetime(2026, 10, 9, 12, 0, 0)
STATE: dict = {}


def _info(name: str, **kw) -> SimpleNamespace:
    base = dict(activity_status="idle", status_source="registry", subagents_running=None, background_open=None, tmux_session=name,
                host_key="local", session_row_id=1, host_label="here",
                session=SimpleNamespace(id=f"ses_{name.removeprefix('cloude_')}", tmux_created_epoch=7, agent_type="claude",
                                        last_activity=datetime.utcnow()))
    base.update(kw)
    return SimpleNamespace(**base)


class View:
    gate_waited = False

    def __init__(self):
        registry = SimpleNamespace(subscribers=STATE.get("subscribers", {}))
        self.infos = [_info("cloude_a"), STATE["target"]]
        self.app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(registry=registry)))

    async def list_infos(self):
        return self.infos

    async def list_session_infos(self):
        return self.infos

    async def list_peer_infos(self):
        return []


@pytest.fixture()
def world(monkeypatch):
    restarts: list = []
    armed = {"on": False}
    STATE.clear()
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    arm_beast(monkeypatch, lambda: armed["on"])
    monkeypatch.setattr(write_tools, "gate_enabled", lambda: True)

    async def pin(manager, target_id):
        return 7, "cloude_b"

    async def live(app, info):
        return True

    async def do_restart(app, target_id, epoch, approved, was_live, account=None, pin=False):
        restarts.append(target_id)
        return {"ok": True}

    monkeypatch.setattr(write_tools.approval_runtime, "pin", pin)
    monkeypatch.setattr(write_tools, "_pane_live", live)
    monkeypatch.setattr(write_tools, "_do_restart", do_restart)

    async def one(manager, args, tool):
        return STATE["target"]

    monkeypatch.setattr(write_tools.session_target, "live_info", one)
    return restarts, armed


def _restart() -> dict:
    return asyncio.run(tools.call_tool(View(), PANE, "session_restart", {"target": "cloude_b"}))


def test_working_session_is_in_use_and_beast_now_lets_a_mid_work_restart_through(world):
    restarts, armed = world
    STATE["target"] = _info("cloude_b", activity_status="working", subagents_running=2)
    armed["on"] = True
    answer = _restart()
    text = str(answer)
    assert "pending" not in text and "2 background agents running" in text and restarts == ["ses_b"]
    armed["on"] = False
    STATE["target"] = _info("cloude_b", activity_status="working", subagents_running=2)
    assert "pending" in str(_restart())
    item = pending.get_store().list()[0]
    assert item["in_use"]["in_flight"] is True
    card = item["display"]["in_use"]
    assert card["tone"] == "alert" and [p["key"] for p in card["parts"]] == ["agents", "working"]


def test_idle_session_with_a_window_open_is_in_view_and_beast_still_runs_it(world):
    restarts, armed = world
    STATE["target"] = _info("cloude_b", activity_status="idle")
    STATE["subscribers"] = {"ses_b": [object()]}
    armed["on"] = True
    answer = _restart()
    assert restarts == ["ses_b"] and "open in 1 windows" in str(answer) and "Nothing proven running" in str(answer)


def test_working_from_a_fresh_registry_observation_is_in_flight_despite_old_input():
    orchestrator = _info("cloude_b", activity_status="working_subagent", status_source="registry")
    orchestrator.session.last_activity = NOW - timedelta(hours=1)
    usage = in_use.summarize(orchestrator)
    assert usage["in_flight"] is True and in_use.blocks_beast(usage, "session_delete") and not in_use.blocks_beast(usage, "session_stop")
    assert usage["signals"] == [{"key": "working", "params": {"source": "registry"}}]
    assert display.build("session_restart", {}, "b", "s", in_use=usage)["in_use"]["tone"] == "alert"


@pytest.mark.parametrize("source", ["transcript", "tmux", "none"])
def test_working_only_a_transcript_supports_is_information_not_in_flight(source):
    old = _info("cloude_b", activity_status="working_subagent", status_source=source)
    old.session.last_activity = NOW - timedelta(days=10)
    usage = in_use.summarize(old)
    assert usage["in_flight"] is False and not in_use.blocks_beast(usage)
    assert usage["signals"][0]["key"] == "stale_working" and usage["signals"][0]["params"]["since"] == "2026-09-29"
    assert f"claims working, only the {source} says so, no activity since 2026-09-29" in in_use.warning(usage)
    assert display.build("session_restart", {}, "b", "s", in_use=usage)["in_use"]["tone"] == "quiet"


def test_a_stale_observation_reads_unknown_so_it_is_not_in_use():
    assert in_use.summarize(_info("cloude_b", activity_status="unknown", status_source="none")) is None


def test_pane_working_is_in_flight_and_quiet_states_are_not_in_use():
    assert in_use.summarize(_info("cloude_b", activity_status="working", status_source="pane"))["in_flight"] is True
    assert in_use.summarize(_info("cloude_b", activity_status="finished_unread")) is None
    assert in_use.summarize(_info("cloude_b", activity_status="question"))["in_flight"] is True
