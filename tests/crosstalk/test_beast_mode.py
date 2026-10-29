
import asyncio
import json
import pytest

from src.api import beast_mode_routes
from src.core.mcp import beast_mode, beast_store, pending
from src.core.mcp.caller import AgentCaller
from tests.python.beast_mode.grid import install


def test_arm_approves_only_scope_and_records_external_identity(monkeypatch, tmp_path):
    store = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", store)
    install(monkeypatch)
    calls = []
    pushed = []
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"mcp": {"enabled": True}, "unrelated": 1}))
    monkeypatch.setattr(beast_mode_routes.settings, "auth_config_file", str(config))

    async def execute():
        calls.append("remote")
        return {"ok": True}

    def add(action, summary, *, beast_eligible=True):
        return store.create(caller_session_id="mcp-token:one", caller_tmux="mcp-token:one",
                            target_session_id="remote:peer:session", target_tmux="session",
                            action=action, args_summary=summary, execute=execute,
                            external_client="token-one", beast_eligible=beast_eligible)

    eligible = add("session_restart", "on hosta: restart")
    loop = add("crosstalk_resume", "resume a paused pair")
    dialog = add("session_send_keys", "YOUR OWN open dialog: type Enter", beast_eligible=False)
    always_waits_tool = "project_delete"
    assert always_waits_tool in beast_mode.ALWAYS_WAITS
    destructive = add(always_waits_tool, "delete a project")

    monkeypatch.setattr(beast_store.resource_push, "notify", pushed.append)
    result = asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True)))

    assert result["approved_count"] == 1 and calls == ["remote"]
    written = json.loads(config.read_text())
    assert written["mcp"]["beast_mode"] is True and written["unrelated"] == 1
    assert pushed == [beast_store.topics.BEAST_MODE]
    assert eligible.status == pending.APPROVED and eligible.approval_source == "approved by beast mode"
    assert loop.status == dialog.status == destructive.status == pending.PENDING
    assert not beast_mode.approval_skip("crosstalk_resume", own_dialog=False)

    caller = AgentCaller("mcp-token:one", "mcp-token:one", "mcp-token:one", token_name="token-one")
    asyncio.run(beast_mode.run_unprompted(caller, "session_send_message", execute,
                                          target_id="remote:peer:session", args={"text": "hello"}))
    recent = store.decided()[0]
    assert recent["external_client"] == "token-one"
    assert recent["approval_source"] == "approved by beast mode"
    assert recent["action"] == "session_send_message"

    async def refuse():
        raise ValueError("refused")

    with pytest.raises(ValueError):
        asyncio.run(beast_mode.run_unprompted(caller, "session_stop", refuse))
    assert store.decided()[0]["result"] == {"status": "failed", "error_type": "ValueError"}

    async def disarm_during_execution():
        await beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=False))
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow():
            entered.set()
            await release.wait()
            return {"ok": True}

        first = store.create(caller_session_id="s", caller_tmux="a", target_session_id="a",
                             target_tmux="a", action="session_restart", args_summary="slow", execute=slow)
        second = store.create(caller_session_id="s", caller_tmux="a", target_session_id="b",
                              target_tmux="b", action="session_stop", args_summary="later", execute=slow)
        arming = asyncio.create_task(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True)))
        await asyncio.wait_for(entered.wait(), 3)
        disarmed = await asyncio.wait_for(
            beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=False)), 3)
        release.set()
        armed_answer = await arming
        assert disarmed["enabled"] is False and armed_answer["enabled"] is False
        assert first.status == pending.APPROVED and second.status == pending.PENDING

    asyncio.run(disarm_during_execution())
