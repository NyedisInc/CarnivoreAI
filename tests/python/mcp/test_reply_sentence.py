
import asyncio
import json

from src.core.mcp import common, reply_sentence, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _fail, _ok


class _Manager:
    async def list_session_infos(self):
        return []


def test_success_and_failure_replies_carry_the_sentence():
    ok = reply_sentence.attach("session_create", {"label": "Cv-Demo"}, _ok({"id": "ses_1"}))
    assert len(ok["content"]) == 2 and json.loads(ok["content"][0]["text"]) == {"id": "ses_1"}
    assert ok["content"][-1] == {"type": "text", "text": "created a session called Cv-Demo", "_meta": {"carnivore_sentence": True}}
    listed = reply_sentence.attach("sessions_list", {}, _ok([]))
    assert listed["content"][-1]["text"] == "listed sessions"
    bad = reply_sentence.attach("session_status", {}, _fail("no live session matches target 'x'"))
    assert bad["isError"] and bad["content"][-1]["text"] == "failed: no live session matches target 'x'"
    again = reply_sentence.attach("sessions_list", {}, listed)
    assert len(again["content"]) == 2


def test_no_secret_rides_and_call_tool_adds_it_once():
    leaked = reply_sentence.attach("x_get", {}, _fail("boom sk-ant-api03-" + "a" * 40))
    assert "sk-ant-api03-" + "a" * 40 not in leaked["content"][-1]["text"]
    result = asyncio.run(tools.call_tool(_Manager(), AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a"), "whoami", {}))
    assert result["isError"] and result["content"][-1]["text"].startswith("failed: your session") and len(result["content"]) == 2


def test_session_target_shows_its_display_name_for_every_shape():
    from types import SimpleNamespace as NS

    def row(sid, tmux, label, host="local"):
        return NS(session=NS(id=sid), tmux_session=tmux, label=label, claude_title=None, host_key=host)

    infos = [row("ses_01020304", "carnivore_x", "Demo Session"), row("adopted:ext", "ext", None),
             row("remote:peer-1:t", "t", "Far Desk", host="peer-1")]
    for target, shown in (("ses_01020304", "Demo Session"), ("carnivore_x", "Demo Session"), ("adopted:ext", "ext"),
                          ("remote:peer-1:t", "Far Desk")):
        reply_sentence.begin_call()
        common._resolve(infos, {"target": target})
        got = reply_sentence.attach("session_background_jobs_list", {"target": target}, _ok([]))
        assert got["content"][-1]["text"] == f"listed session background jobs ({shown})"
    reply_sentence.begin_call()
    assert reply_sentence.attach("session_status", {"target": "ses_nope"}, _ok({}))["content"][-1]["text"] == "checked the status of session (ses_nope)"
