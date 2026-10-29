from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_auto_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_auto_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import HTTPException  # noqa: E402

from src.api import automation_run_routes  # noqa: E402
from src.core.automations import gates, models as m  # noqa: E402
from src.core.automations.targets.agent_def import AgentDef  # noqa: E402

CONVERSATION = "11111111-2222-4333-8444-555555555555"


def _accepts(tools, permission="edits_in_folder") -> bool:
    try:
        AgentDef(folder="/x", prompt="p", tools=tools, permission=permission)
    except ValueError:
        return False
    return True


def test_a_pattern_may_hold_spaces_but_never_smuggle_a_second_tool():
    assert _accepts(["Read", "Grep"], "read_only")
    assert _accepts(["Edit", "Bash(git status)"])
    assert _accepts(["Bash(npm run test:*)", "Bash(git log --oneline)"])
    assert not _accepts(["Bash(git status)"], "read_only")
    for smuggled in (["Read", "Grep(x),Bash(rm -rf ~)"], ["Grep(x),Edit(x)"], ["Read Bash"], ["Bash(a (b))"], ["Bash(a,b)"],
                     ["Bash( x)"], ["Bash(x )"], ["Bash(a\tb)"]):
        assert not _accepts(smuggled, "read_only"), smuggled
        assert not _accepts(smuggled), smuggled


@pytest.fixture
def world(tmp_path, monkeypatch):
    folder = tmp_path / "proj"
    folder.mkdir()
    launches: list = []

    class Manager:

        async def create_session(self, **kwargs):
            launches.append(kwargs)
            return SimpleNamespace(id="ses_new", tmux_session="carnivore_new", working_dir=kwargs["working_dir"],
                                   model_dump=lambda **_: {})

    runs = {
        "run_ok": {"automation_id": "aut_1", "report": {"conversation_uuid": CONVERSATION, "folder": str(folder)}},
        "run_none": {"automation_id": "aut_1", "report": {"final_text": "x"}},
        "run_blank": {"automation_id": "aut_1", "report": None},
        "run_gone": {"automation_id": "aut_2", "report": {"conversation_uuid": CONVERSATION, "folder": str(folder)}},
    }
    autos = {"aut_1": {"name": "nightly", "target": {"kind": "agent", "login_account_id": "acct-b"}}}

    def get(automation_id):
        if automation_id not in autos:
            raise m.AutomationNotFound(automation_id)
        return autos[automation_id]

    def run(run_id):
        if run_id not in runs:
            raise m.AutomationNotFound(run_id)
        return runs[run_id]

    monkeypatch.setattr(gates, "login_of", lambda target: (target.get("login_account_id"), "/profile/b"))
    state = SimpleNamespace(automation_store=SimpleNamespace(run=run, get=get), session_manager=Manager())
    return SimpleNamespace(request=SimpleNamespace(app=SimpleNamespace(state=state)), launches=launches, folder=folder)


def test_continue_resumes_the_conversation_in_the_agents_folder_and_login(world):
    asyncio.run(automation_run_routes.continue_run_in_session(world.request, "run_ok"))
    assert len(world.launches) == 1
    launch = world.launches[0]
    assert launch["agent_extra_args"] == ["--resume", CONVERSATION]
    assert launch["working_dir"] == str(world.folder)
    assert launch["claude_account"] == "acct-b"
    assert launch["auto_start_claude"] is True and launch["label"] == "nightly (continued)"


@pytest.mark.parametrize("run_id,status,code", [("run_none", 409, "no_conversation"), ("run_blank", 409, "no_conversation"),
                                                ("run_gone", 409, "automation_gone"), ("run_missing", 404, "run_not_found")])
def test_continue_refuses_a_run_it_cannot_resume(world, run_id, status, code):
    with pytest.raises(HTTPException) as refused:
        asyncio.run(automation_run_routes.continue_run_in_session(world.request, run_id))
    assert refused.value.status_code == status and refused.value.detail["code"] == code
    assert world.launches == []
