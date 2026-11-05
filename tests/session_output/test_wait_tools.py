
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.mcp import session_target, wait_tools, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.session_output import waits

CALLER = AgentCaller(session_id="ses_lead", tmux_name="lead", current_session_id="ses_lead")


def _info(host_key=LOCAL_HOST_KEY, status="working"):
    return SimpleNamespace(host_key=host_key, activity_status=status, session=SimpleNamespace(id="ses_t"))


class Manager:
    def __init__(self, path=None):
        self.path = path

    def has_session(self, _sid):
        return True

    def pipe_basis(self, _sid):
        return (lambda: (self.path, 1.0)) if self.path else None


def _body(result):
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def target(monkeypatch):
    holder = {"info": _info()}

    async def live_info(_m, _a, _t=""):
        return holder["info"]

    monkeypatch.setattr(session_target, "live_info", live_info)
    return holder


@pytest.mark.asyncio
@pytest.mark.parametrize("args, why", [
    ({"target": "t", "until": {}}, "until needs"),
    ({"target": "t", "until": {"state": ["busy"]}}, "until.state"),
    ({"target": "t", "until": {"output_contains": "a\nb"}}, "one line"),
    ({"target": "t", "until": {"output_contains": "x" * 201}}, "one line"),
    ({"target": "t", "until": {"state": ["idle"]}, "timeout": 51}, "timeout"),
    ({"target": "t", "until": {"state": ["idle"]}, "min_quiet": 11}, "min_quiet"),
    ({"target": "t", "until": {"state": ["idle"]}, "since": "nope"}, "cursor"),
])
async def test_bad_arguments_are_refused(target, args, why):
    with pytest.raises(ToolError, match=why):
        await wait_tools.session_wait(Manager(), CALLER, args)


@pytest.mark.asyncio
async def test_an_output_wait_on_a_paired_computer_is_refused(target):
    target["info"] = _info(host_key="peer-ab")
    with pytest.raises(ToolError, match="state waits only"):
        await wait_tools.session_wait(Manager(), CALLER, {"target": "t", "until": {"output_contains": "done"}})


@pytest.mark.asyncio
async def test_a_state_already_reached_matches_at_once(target, tmp_path):
    target["info"] = _info(status="idle")
    (tmp_path / "p").write_bytes(b"")
    body = _body(await wait_tools.session_wait(Manager(tmp_path / "p"), CALLER,
                                               {"target": "t", "until": {"state": ["idle", "exited"]}, "timeout": 2}))
    assert body["status"] == "matched" and body["matched"] == "state:idle" and body["cursor"].startswith("c1.")


@pytest.mark.asyncio
async def test_send_and_wait_hands_back_the_pending_id_and_the_pre_send_cursor(target, tmp_path, monkeypatch):
    (tmp_path / "p").write_bytes(b"old output")
    sent = []

    async def send(_m, _c, args):
        sent.append(args)
        return _ok({"status": "pending", "id": "act_1"})

    monkeypatch.setattr(write_tools, "session_send_message", send)
    body = _body(await wait_tools.session_send_and_wait(Manager(tmp_path / "p"), CALLER, {"target": "t", "text": "go"}))
    assert sent == [{"target": "ses_t", "text": "go"}]
    assert body["status"] == "pending" and body["id"] == "act_1" and body["cursor"].endswith(".10")


@pytest.mark.asyncio
async def test_send_and_wait_ends_as_blocked_on_a_dialog(target, tmp_path, monkeypatch):
    (tmp_path / "p").write_bytes(b"")

    async def send(_m, _c, _args):
        waits.REGISTRY.on_status("ses_t", "question")
        return _ok({"status": "delivered", "id": "m1"})

    async def dialog(_m, _i):
        return {"kind": "permission", "question": "Allow rm?", "options": [{"label": "Yes"}, {"label": "No"}]}

    monkeypatch.setattr(write_tools, "session_send_message", send)
    from src.core.mcp import dialog_tools
    monkeypatch.setattr(dialog_tools, "_shown_dialog", dialog)
    real_run = waits.run_wait

    async def run_wait(**kw):
        import asyncio
        task = asyncio.ensure_future(real_run(**kw))
        await asyncio.sleep(0.05)
        waits.REGISTRY.on_status("ses_t", "question")
        return await task

    monkeypatch.setattr(waits, "run_wait", run_wait)
    body = _body(await wait_tools.session_send_and_wait(Manager(tmp_path / "p"), CALLER,
                                                        {"target": "t", "text": "go", "timeout": 3}))
    assert body["status"] == "blocked" and body["dialog"] == {"kind": "permission", "question": "Allow rm?",
                                                              "options": ["Yes", "No"]}
    assert body["sent"] == {"id": "m1", "status": "delivered"}
