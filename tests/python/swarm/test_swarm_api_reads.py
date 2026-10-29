
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import swarm_routes
from src.api.auth import require_auth
from src.config import settings
from src.core import resource_push
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm import push, store, stream, thread_port
from src.cplugs.huddle import swarm_stream, rules


def msg(i, author_key, text, at, author="claude"):
    return {"id": i, "item_id": 1, "author": author, "author_key": author_key, "kind": "reply", "text": text,
            "answered": False, "created_at": at, "seq": i, "unread": False}


def item(i, kind, status, at, swarm_ref=None, thread=()):
    return {"id": i, "list": "agent:1", "swarm_ref": swarm_ref, "kind": kind, "status": status, "created_at": at,
            "thread": list(thread), "text": "t"}


def test_conversation_entries_are_oldest_first_and_skip_swarm_event_lines():
    chat = item(1, "", "open", 1.0, "chat", [
        msg(1, rules.OWNER_KEY, "do it", 5.0, "joe"), msg(2, rules.SWARM_KEY, "event line", 6.0),
        msg(3, "sess-key", "on it", 7.0)])
    cards = [item(2, "question", "question", 2.0), item(3, "done", "review", 3.0), item(4, "done", "done", 4.0),
             item(5, "waiting", "open", 8.0), item(6, "", "open", 9.0)]
    got = swarm_stream.entries({"items": [chat, *cards]})
    assert [(e["id"], e["kind"]) for e in got] == [
        ("item:2", "card"), ("item:3", "card"), ("item:4", "card"), ("msg:1", "owner"), ("msg:3", "agent"),
        ("item:5", "card"), ("item:6", "card")]
    assert [e["card"] for e in got if e["kind"] == "card"] == ["question", "review", "done", "review", "info"]
    assert got[3]["text"] == "do it" and got[3]["at"] == 5.0


def test_window_after_a_cursor_and_merge_with_another_source():
    entries = [{"id": f"msg:{i}", "at": float(i), "kind": "owner", "text": "x"} for i in range(1, 6)]
    assert [e["id"] for e in stream.window(entries, "msg:3", 10)] == ["msg:4", "msg:5"]
    assert [e["id"] for e in stream.window(entries, "gone", 2)] == ["msg:4", "msg:5"]
    other = [{"id": "x:1", "at": 2.5, "kind": "agent", "text": "y"}]
    assert [e["id"] for e in stream.merge(entries, other)][:4] == ["msg:1", "msg:2", "x:1", "msg:3"]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"config_version": 5, "projects": []}))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path))
    monkeypatch.setattr(settings, "_auth_config_cache", None)
    assert ensure_db_migrated(tmp_path).status == "ok"

    class Manager:
        async def list_session_infos(self):
            return []

    class Port:
        async def ensure_thread(self, key, title): ...
        async def read_thread(self, key, limit): return []
        async def open_cards(self): return []

    thread_port.register(Port())
    app = FastAPI()
    app.include_router(swarm_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = Manager()
    yield SimpleNamespace(app=app, manager=app.state.session_manager, state=tmp_path, config=config)
    thread_port.register(None)
    settings._auth_config_cache = None


@pytest.mark.asyncio
async def test_create_roster_detail_mcp_and_validation(world, tmp_path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=world.app), base_url="http://t/api/v1") as c:
        repo = str(tmp_path / "r")
        made = await c.post("/swarm/agents", json={"repo_dir": repo, "job": "Fix Login!", "rank": "task"})
        assert made.status_code == 201 and made.json()["slug"] == "fix-login" and made.json()["memory_scope"] == "local"
        again = await c.post("/swarm/agents", json={"repo_dir": repo, "job": "Fix Login!", "rank": "task"})
        assert again.json()["slug"] == "fix-login-2"
        assert (await c.post("/swarm/agents", json={"repo_dir": "rel/dir", "job": "j", "rank": "task"})).status_code == 422
        assert (await c.post("/swarm/agents", json={"repo_dir": repo, "job": "j", "rank": "alpha"})).status_code == 422
        assert (await c.post("/swarm/agents", json={"repo_dir": repo, "job": "j", "rank": "task", "parent_id": 99})).status_code == 422
        roster = (await c.get("/swarm/roster")).json()
        assert [a["id"] for a in roster["agents"]] == [1, 2] and roster["limits"]["live_bodies"] == 0
        asleep = roster["agents"][0]
        assert asleep["state"] == "asleep" and asleep["session_id"] is None
        assert asleep["session_row_id"] is None and asleep["session_uuid"] is None
        with closing(connect(db_path_for(world.state), create=False)) as conn:
            conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin, "
                "lifecycle, created_at, updated_at) VALUES ('uuid-fix', 'cloude', 'cloude_fix', 100, '/tmp/pk', 't', 'created', "
                "'stopped', '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z')")
            row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'uuid-fix'").fetchone()[0]
            store.set_session_row(conn, 1, row_id)
        woken = (await c.get("/swarm/roster")).json()["agents"][0]
        assert woken["state"] == "asleep" and woken["session_id"] is None
        assert woken["session_row_id"] == row_id and woken["session_uuid"] == "uuid-fix"
        assert (await c.get("/swarm/agents/99")).status_code == 404
        assert (await c.get("/swarm/agents/1/conversation?limit=0")).status_code == 422
        assert (await c.get("/swarm/agents/1/conversation")).json() == {"entries": [], "cursor": None}
        thread_port.register(None)
        assert (await c.get("/swarm/agents/1")).json()["detail"]["code"] == "swarm_off"
        assert (await c.get("/swarm/roster")).json()["threads_ready"] is False
        assert (await c.get("/swarm/settings")).json()["max_live_bodies"] is None
        put = await c.put("/swarm/settings", json={"max_live_bodies": 7})
        assert put.json()["max_live_bodies"] == 7 and json.loads(world.config.read_text())["swarm"]["max_live_bodies"] == 7
        assert (await c.put("/swarm/settings", json={"max_live_bodies": 0})).status_code == 422
        page = (await c.get("/swarm/settings")).json()
        assert (page["page_default_view"], page["panel_default_density"], page["character_pack"]) == ("tree", "expanded", "theme")
        put = await c.put("/swarm/settings", json={"page_default_view": "org", "panel_default_density": "detailed", "character_pack": "pixel"})
        assert put.json()["page_default_view"] == "org" and put.json()["max_live_bodies"] == 7
        assert json.loads(world.config.read_text())["swarm"]["character_pack"] == "pixel"
        for bad in ({"page_default_view": "grid"}, {"panel_default_density": "huge"}, {"character_pack": "Bad Name"}):
            assert (await c.put("/swarm/settings", json=bad)).status_code == 422
        look = (await c.get("/swarm/settings")).json()
        assert look["color_mode"] == "project" and look["animations"] == {}
        assert look["shapes"] == {"sysop": "square", "company": "square", "project": "square", "agent": "square"}
        put = await c.put("/swarm/settings", json={"color_mode": "random", "shapes": {"company": "hexagon", "sysop": "cloud"},
                                                  "animations": {"idle": "none", "working": "pulse"}})
        assert put.status_code == 200
        put = await c.put("/swarm/settings", json={"shapes": {"project": "triangle"}, "animations": {"working": "think-orbit"}})
        look = (await c.get("/swarm/settings")).json()
        assert look["color_mode"] == "random" and look["max_live_bodies"] == 7
        assert look["shapes"] == {"sysop": "cloud", "company": "hexagon", "project": "triangle", "agent": "square"}
        assert look["animations"] == {"idle": "none", "working": "think-orbit"}
        cleared = (await c.put("/swarm/settings", json={"max_live_bodies": None})).json()
        assert cleared["max_live_bodies"] is None and cleared["color_mode"] == "random"
        assert json.loads(world.config.read_text())["swarm"]["shapes"]["company"] == "hexagon"
        for bad in ({"color_mode": "rainbow"}, {"shapes": {"company": "blob"}}, {"shapes": {"boss": "star"}},
                    {"animations": {"idle": "moonwalk"}}, {"animations": {"napping": "none"}}):
            assert (await c.put("/swarm/settings", json=bad)).status_code == 422

    thread_port.register(SimpleNamespace(read_thread=lambda key, limit: asyncio.sleep(0, result=[]),
                                         open_cards=lambda: asyncio.sleep(0, result=[])))
    caller = AgentCaller("ses_1", "cloude_a", "ses_1", scope="read")

    async def ask(name, args):
        return await tools.call_tool(world.manager, caller, name, args)

    def body(answer):
        return json.loads(answer["content"][0]["text"])

    assert [a["id"] for a in body(await ask("swarm_roster", {}))["agents"]] == [1, 2]
    assert body(await ask("swarm_agent", {"agent_id": 2}))["slug"] == "fix-login-2"
    assert body(await ask("swarm_conversation", {"agent_id": 1})) == {"entries": [], "cursor": None}
    missing = await ask("swarm_agent", {"agent_id": 9})
    assert missing["isError"] and "no such agent" in missing["content"][0]["text"]


def test_notify_thread_names_the_agent_topic_of_its_thread(world, monkeypatch):
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        agent = store.create_agent(conn, slug="loki", rank="feature", job="j", display_name="Loki", repo_dir=str(world.state),
                                   effort="high")
    seen = []
    monkeypatch.setattr(resource_push, "notify", seen.append)
    push.notify_thread(agent["thread_key"])
    push.notify_thread("12")
    assert seen == [f"swarm_agent:{agent['id']}"]
