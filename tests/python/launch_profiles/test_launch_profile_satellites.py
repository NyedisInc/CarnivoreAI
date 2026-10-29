
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.api import blueprints_launch, blueprints_peer_member, peer_route_guard
from src.config import settings
from src.core.mcp import pending, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.models.blueprints import BlueprintSession
from tests.python.launch_profiles.test_launch_profile_create import _row, env  # noqa: F401

MEMBER = {"label": "api", "family": "codex", "model": "gpt-x", "opening_prompt": "start the api work",
          "folder": {"mode": "existing", "path": "/work/api"}}
GOLDEN_BLUEPRINT_BODY = ('{"working_dir":"/work/api","project_name":"api","label":"api","cols":120,"rows":40,'
                         '"agent_type":"codex","model":"gpt-x","account_pinned":false,"opening_prompt":"start the api work"}')
GOLDEN_PEER_BODY = ('{"working_dir":"/work/api","project_name":"api","label":"api","agent_type":"codex",'
                    '"model":"gpt-x","opening_prompt":"start the api work","cols":120,"rows":40,"host_key":"local"}')


@pytest.mark.asyncio
async def test_blueprint_and_peer_bodies_are_byte_identical_to_the_golden_bodies(monkeypatch):
    seen: dict = {}

    async def fake_create(request, body):
        seen["blueprint"] = body.model_dump_json(exclude_none=True, exclude={"auto_start_claude", "copy_templates"})
        return SimpleNamespace(id="ses_x", tmux_session="t")

    monkeypatch.setattr("src.api.session_crud_routes.create_session", fake_create)
    monkeypatch.setattr(blueprints_launch, "_row_identity", lambda *a: (None, None))
    member = BlueprintSession.model_validate(MEMBER)
    await blueprints_launch.create_member_session(SimpleNamespace(), member, "/work/api", 120, 40)

    async def fake_forward(rule, peer, path, sent):
        seen["peer"] = json.dumps(sent, separators=(",", ":"))
        return SimpleNamespace(status_code=201, body=json.dumps({"id": "remote:peer-ab:t"}))

    peer = SimpleNamespace(key="peer-ab", label="far")
    monkeypatch.setattr(blueprints_peer_member, "_target", lambda key: peer)
    monkeypatch.setattr(blueprints_peer_member, "_shadow_row", lambda *a: (1, "u"))
    monkeypatch.setattr(peer_route_guard, "forward_reply", fake_forward)
    member = BlueprintSession.model_validate({**MEMBER, "host_key": "peer-ab"})
    await blueprints_peer_member.create_peer_member(member, 120, 40)
    assert seen["blueprint"] == GOLDEN_BLUEPRINT_BODY
    assert seen["peer"] == GOLDEN_PEER_BODY


def _caller() -> AgentCaller:
    return AgentCaller(session_id="ses_c", tmux_name="carnivore_c", current_session_id="ses_c")


async def _live_ids() -> set:
    return set()


@pytest.mark.asyncio
async def test_mcp_create_with_a_launch_profile_writes_it_to_the_launch_record(env, tmp_path, monkeypatch):  # noqa: F811
    from src.core.session_manager import SessionManager

    mgr = SessionManager()
    mgr.gate_waited = True
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    app = SimpleNamespace(state=SimpleNamespace(session_manager=mgr))
    view = SimpleNamespace(app=app, live_ids_now=_live_ids)
    work = tmp_path / "wd"
    work.mkdir()
    receipt = await write_tools.session_create(view, _caller(), {"working_dir": str(work), "launch_profile": "claude-or"})
    queued = json.loads(receipt["content"][0]["text"])
    assert queued["status"] == "pending"
    item = pending.get_store().get(queued["id"])
    assert item.action == "session_create" and item.args["agent_type"] == "claude-or"
    approved = await pending.get_store().approve(queued["id"])
    assert approved.result is not None and not approved.result.get("isError")
    payload = json.loads(approved.result["content"][0]["text"])
    try:
        assert payload["launch"]["id"] == "claude-or" and payload["launch"]["harness"] == "claude"
        assert payload["launch"]["model"] == "m-1" and payload["launch"]["permissions_badge"]
        session = SimpleNamespace(tmux_session="carnivore_wd")
        record = json.loads(_row(env, session)["launch_record"])
        assert record["profile"] == "claude-or" and record["endpoint"]["connection_id"] == "or"
    finally:
        await mgr.destroy_session(payload["id"])
    for bad, why in (({"launch_profile": "claude-or", "agent_type": "codex"}, "different launches"),
                     ({"launch_profile": "nope-profile"}, "no launch profile"),
                     ({"launch_profile": "claude-or", "peer": "far"}, "paired computer")):
        with pytest.raises(ToolError, match=why):
            await write_tools.session_create(view, _caller(), {"working_dir": str(work), **bad})


def test_opening_prompt_and_rename_reach_the_agent_through_the_resolved_plan(env):  # noqa: F811
    sink: list = []
    command = settings.get_agent_command("claude-plain", extra_args=["--name", "api", "do the thing"],
                                         pane_launch=True, plan_sink=sink)
    assert sink[0].purpose == "pane" and sink[0].argv_tail[-3:] == ("--name", "api", "do the thing")
    assert "'do the thing'" in command or '"do the thing"' in command
