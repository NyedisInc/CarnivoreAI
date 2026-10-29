
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_1417_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_1417_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, owner_message, spawn, store, thread_port, watch
from src.cplugs.host import runtime
from src.cplugs.huddle import routes as huddle_routes
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.owner import turn_on

CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")
FINAL = "**Done.** The models are swapped.\n\n- haiku for the scout\n- opus for review\n\n```\nswap ok\n```"
EPOCH = 1760000000


def _record(kind: str, **fields):
    return {"type": kind, "isSidechain": False, "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **fields}


def _assistant(msg_id: str, stop: str, *blocks):
    return [_record("assistant", message={"id": msg_id, "role": "assistant", "stop_reason": stop, "content": [b]}) for b in blocks]


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    from src.config import settings
    from src.core.swarm import delivery
    from src.core.session_token_usage import claude_reader

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, CURRENT_SCHEMA_VERSION)
        alpha = store.create_agent(conn, slug="alpha", rank="alpha", job="j", display_name="Alpha", repo_dir=str(tmp_path), effort="high")
        loki = store.create_agent(conn, slug="loki", rank="project", job="j", display_name="Loki", repo_dir=str(tmp_path),
                                  effort="high", parent_id=alpha["id"])
        assert store.cas_state(conn, loki["id"], loki["state"], "awake")
        loki = store.get_agent(conn, loki["id"])
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    ctx = host.context("huddle")
    port = TaskManagerSwarmPort(ctx)
    ctx.swarm.register_thread_port(port)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    pasted = []

    async def _no_infos():
        return []

    async def live_info(app_state, agent):
        return SimpleNamespace(tmux_session=None, session=SimpleNamespace(id="ses_1"), startup_gate=None)

    async def paste(request, session_id, text):
        pasted.append(text)

    async def parent_agent(view, caller):
        return loki

    transcript = tmp_path / "conv.jsonl"
    monkeypatch.setattr(body, "live_info", live_info)
    monkeypatch.setattr("src.api.one_shot_routes.paste_through_gates", paste)
    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    monkeypatch.setattr(claude_reader, "locate_transcript", lambda uuid, working_dir=None: SimpleNamespace(path=transcript))
    monkeypatch.setattr(delivery, "_pending", {})
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, manager=SimpleNamespace(app=app, gate_waited=True, list_session_infos=_no_infos), loki=loki, port=port,
                              pasted=pasted, transcript=transcript, app_state=SimpleNamespace())
    thread_port.register(None)
    watch.reset()


def _agent_texts(world):
    return [e["text"] for e in asyncio.run(world.port.read_thread(world.loki["thread_key"], 50)) if e["kind"] == "agent"]


def _reading(state: str, turn_end):
    return SimpleNamespace(verdict=SimpleNamespace(state=state, reason="idle"),
                           evidence=SimpleNamespace(dialog=None, identity=("cloude", "cloude_a", EPOCH, 1, "conv-1"),
                                                    transcript=SimpleNamespace(turn_end_at=turn_end)))


async def _pass(world, state: str, turn_end) -> None:
    watch.on_observation(SimpleNamespace(key=f"cloude_a@{EPOCH}"), _reading(state, turn_end))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
            return


def test_owner_turn_posts_the_agents_final_text_once(world):
    out = asyncio.run(owner_message.post_owner_message(world.app_state, world.loki["id"], "swap the models"))
    assert out.outcome == "delivered" and len(world.pasted) == 1
    assert "swarm_say" not in world.pasted[0]
    assert world.pasted[0] == f"swap the models\n\n{owner_message.REF_LINE.format(ref=out.message_ref)}"
    from src.core.swarm import reply_mirror

    reply_mirror.reset()
    reply_mirror.note_owner_delivery(world.loki["id"])
    prompt = _record("user", promptId="p-1", uuid="u-1", message={"role": "user", "content": world.pasted[0]})
    middle = _assistant("m1", "tool_use", {"type": "thinking", "thinking": "plan"},
                        {"type": "tool_use", "id": "t1", "name": "mcp__carnivore__swarm_say", "input": {}})
    world.transcript.write_text("".join(json.dumps(r) + "\n" for r in [prompt, *middle]))
    watch.register(world.app_state, "cloude_a", world.loki["id"], EPOCH)
    watch._unsettled.clear()

    async def scenario():
        await _pass(world, "busy", None)
        said = await tools.call_tool(world.manager, CALLER, "swarm_say", {"text": "a reworded second copy"})
        assert json.loads(said["content"][0]["text"])["held"] is True
        tail = [_record("user", promptId="p-1", message={"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "held"}]}),
                *_assistant("m2", "end_turn", {"type": "thinking", "thinking": "wrap up"}, {"type": "text", "text": FINAL})]
        with world.transcript.open("a") as stream:
            stream.write("".join(json.dumps(r) + "\n" for r in tail))
        ended = datetime.now(timezone.utc)
        await _pass(world, "idle", ended)
        await _pass(world, "needs_user", ended)
        reply_mirror.reset()
        reply_mirror.note_owner_delivery(world.loki["id"])
        await _pass(world, "idle", ended)

    asyncio.run(scenario())
    assert _agent_texts(world) == [FINAL]
