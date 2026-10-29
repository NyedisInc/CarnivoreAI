
from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_bv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_bv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.mcp import in_use, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.protocol import BatchView
from src.core.subagents.tally import SubagentTally
from src.models import Session, SessionInfo


class _Watcher:

    def observation_for(self, session_id, now=None):
        evidence = SimpleNamespace(subagents=SubagentTally("ok", running=2, total=5, unknown=0),
                                   transcript=SimpleNamespace(verdict="unreadable"))
        return SimpleNamespace(stale=False, evidence=evidence)


class _Manager:

    def __init__(self):
        self._attention_watcher = _Watcher()
        self.infos = [SessionInfo(session=Session(id="ses_a", working_dir="/tmp"), agent_family="claude",
                                  tmux_session="cloude_a", host_key="local", activity_status="working")]

    async def list_session_infos(self):
        return self.infos


def _view():
    manager = _Manager()
    return manager, BatchView(manager, SimpleNamespace(state=SimpleNamespace(session_manager=manager)))


def test_the_bare_manager_rows_carry_no_agent_count():
    manager, _ = _view()
    rows = asyncio.run(manager.list_session_infos())
    assert rows, "the subject must be present before its absence means anything"
    assert rows[0].subagents_running is None


def test_the_view_stamps_the_running_agents():
    _, view = _view()
    rows = asyncio.run(view.list_session_infos())
    assert rows and rows[0].subagents_running == 2 and rows[0].subagents_total == 5


def test_session_status_and_the_in_use_warning_see_the_agents():
    _, view = _view()
    caller = AgentCaller("ses_x", "cloude_x", "ses_x")
    out = asyncio.run(tools.call_tool(view, caller, "session_status", {"target": "ses_a"}))
    assert '"subagents_running": 2' in str(out) or "'subagents_running': 2" in str(out)
    info = asyncio.run(view.list_session_infos())[0]
    summary = in_use.summarize(info)
    assert summary is not None and {"key": "agents", "params": {"count": "2"}} in summary["signals"]
