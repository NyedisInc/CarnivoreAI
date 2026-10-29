
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_p6_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_p6_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import HTTPException

from src.core import db
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, peer_links, shadow_rows
from src.core.mcp import federated, protocol, tools
from src.core.mcp.caller import AgentCaller
from src.core.pack.placement import explain
from src.core.pack.placement.workload import resolve
from src.core.pack.span import proxy_server
from src.core.swarm import body, body_create, store, thread_port

from tests.python.pack.test_placement import A as INSTALL_A, B as INSTALL_B, C as INSTALL_C, FakeWired, snap

BODY_UUID, BODY_EPOCH = "body-uuid-0001", 1788821572


class Port:

    def __init__(self) -> None:
        self.cards, self.traffic = [], []

    async def ensure_thread(self, key, title): ...
    async def settle_cards(self, ref, **kw): ...
    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref))
        return len(self.cards)
    async def post_traffic(self, key, text, ref):
        self.traffic.append((key, text, ref))
        return f"huddle:msg:{len(self.traffic)}"
    async def close_card(self, item_id, state): ...
    async def archive_thread(self, key): ...


def _session(conn, uuid: str, tmux: str, origin: str, host_key: str = "local") -> int:
    conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin, lifecycle, "
                 "created_at, updated_at, host_key) VALUES (?, 'cloude', ?, ?, '/tmp/p6', 't', ?, 'running', '2026-03-01T00:00:00Z', "
                 "'2026-09-08T00:00:00Z', ?)", (uuid, tmux, BODY_EPOCH, origin, host_key))
    return conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    dirs = {"A": tmp_path / "a", "B": tmp_path / "b"}
    for path in dirs.values():
        path.mkdir()
        assert ensure_db_migrated(path).status == "ok"
    current = {"dir": dirs["A"]}
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: current["dir"], raising=True)
    port = Port()
    thread_port.register(port)
    repo = tmp_path / "repo"
    repo.mkdir()
    ids = {}
    with closing(connect(db_path_for(dirs["A"]), create=False)) as conn, conn:
        for iid, label in ((INSTALL_B, "studio"), (INSTALL_C, "third")):
            peer_hosts.upsert(conn, install_id=iid, label=label, grant_id=f"g-{iid}", fid=f"f-{iid}", initiator=True)
        key_b, key_c = peer_hosts.get(conn, INSTALL_B).key, peer_hosts.get(conn, INSTALL_C).key
        project = body_create.register_project(conn, str(repo), "repo")
        uid = conn.execute("SELECT uid FROM projects WHERE id = ?", (project["id"],)).fetchone()[0]
        boss_row = _session(conn, "uuid-boss", "cloude_boss", "created")
        boss = store.create_agent(conn, slug="boss", rank="project", job="boss", display_name="Boss", repo_dir=str(repo), effort="high",
                                  project_id=project["id"])
        store.set_session_row(conn, boss["id"], boss_row)
        store.cas_state(conn, boss["id"], "asleep", "awake")
        task = store.create_agent(conn, slug="t1", rank="task", job="job of t1", display_name="T1", repo_dir=str(repo), effort="high",
                                  parent_id=boss["id"], goal="goal of t1", task_type="refactor", host_key=key_b)
        shadow_row = _session(conn, shadow_rows.shadow_uuid(INSTALL_B, BODY_UUID), "carnivore_t1", shadow_rows.PEER_ORIGIN, key_b)
        store.set_session_row(conn, task["id"], shadow_row)
        store.cas_state(conn, task["id"], "asleep", "awake")
        ids = {"uid": uid, "boss": boss["id"], "task": task["id"], "shadow": shadow_row, "key_c": key_c}
    with closing(connect(db_path_for(dirs["B"]), create=False)) as conn, conn:
        body_row = _session(conn, BODY_UUID, "carnivore_t1", "created")
        conn.execute("INSERT INTO swarm_remote_bodies (session_row_id, home_install_id, home_agent_id, project_uid, rank, slug, mirror_dir, "
                     "created_at) VALUES (?, ?, ?, ?, 'task', 't1', '/tmp/p6-mirror', '2026-09-08T00:00:00Z')",
                     (body_row, INSTALL_A, ids["task"], uid))
        ids["body_row"] = body_row

    async def peer_infos(**kw):
        return [SimpleNamespace(session_row_id=ids["shadow"], session=SimpleNamespace(tmux_created_epoch=BODY_EPOCH))]

    monkeypatch.setattr(federated, "peer_infos", peer_infos)
    home_info = SimpleNamespace(session=SimpleNamespace(id=f"remote:{key_b}:carnivore_t1"), tmux_session="carnivore_t1", session_row_id=ids["shadow"])

    async def home_infos():
        return [home_info]

    home_view = SimpleNamespace(list_session_infos=home_infos, app=SimpleNamespace(state=SimpleNamespace()), fresh=lambda: home_view)
    monkeypatch.setattr(protocol, "BatchView", lambda manager, app: home_view)
    yield SimpleNamespace(dirs=dirs, current=current, ids=ids, port=port, app=SimpleNamespace(state=SimpleNamespace(session_manager=None)))
    thread_port.register(None)
    peer_links.LINKS = None


class HomeLink:

    def __init__(self, world, as_install: str) -> None:
        self.world, self.as_install, self.sent = world, as_install, []

    def client(self, install_id: str):
        return self if install_id == INSTALL_A else None

    def capabilities(self, install_id: str):
        return ["swarm.proxy", "task_manager.names"]

    async def request(self, method, path, json=None, timeout=None):
        self.sent.append(json)
        self.world.current["dir"] = self.world.dirs["A"]
        try:
            reply = await proxy_server.run(self.world.app, self.as_install, proxy_server.ProxyCall(**json))
            return SimpleNamespace(status_code=200, json=lambda: reply)
        except HTTPException as exc:
            return SimpleNamespace(status_code=exc.status_code, json=lambda: {"detail": exc.detail})
        finally:
            self.world.current["dir"] = self.world.dirs["B"]


def _reports(world):
    with closing(connect(db_path_for(world.dirs["A"]), create=False)) as conn:
        return [dict(r) for r in conn.execute("SELECT agent_id, summary FROM swarm_reports")]


def test_a_remote_body_reports_to_the_home_board_and_a_forged_binding_is_refused(world, monkeypatch):
    world.current["dir"] = world.dirs["B"]
    link = HomeLink(world, INSTALL_B)
    peer_links.LINKS = link
    b_info = SimpleNamespace(session=SimpleNamespace(id="ses_body", tmux_created_epoch=BODY_EPOCH), tmux_session="carnivore_t1",
                             session_row_id=world.ids["body_row"])

    async def b_infos():
        return [b_info]

    b_view = SimpleNamespace(list_session_infos=b_infos, app=SimpleNamespace(state=SimpleNamespace()), fresh=lambda: b_view)
    caller = AgentCaller(session_id="ses_body", tmux_name="carnivore_t1", current_session_id="ses_body")

    answer = asyncio.run(tools.call_tool(b_view, caller, "swarm_report", {"summary": "t1 refactored the module", "done_items": ["one"]}))
    assert not answer.get("isError"), answer
    assert link.sent[0]["body_session_uuid"] == BODY_UUID and link.sent[0]["home_agent_id"] == world.ids["task"]
    landed = _reports(world)
    assert [r["agent_id"] for r in landed] == [world.ids["task"]] and landed[0]["summary"].startswith("t1 refactored the module")
    assert any(ref for _, _, ref in world.port.cards + world.port.traffic)

    plain = SimpleNamespace(session=SimpleNamespace(id="ses_plain", tmux_created_epoch=1), tmux_session="x", session_row_id=999)
    assert asyncio.run(proxy_server.proxy_client.maybe_forward(SimpleNamespace(list_session_infos=lambda: _async([plain])),
                                                                 AgentCaller(session_id="ses_plain", tmux_name="x", current_session_id="ses_plain"),
                                                                 "swarm_report", {})) is None

    world.current["dir"] = world.dirs["A"]
    for who, uuid in ((INSTALL_C, BODY_UUID), (INSTALL_B, "forged-uuid-9999")):
        call = proxy_server.ProxyCall(tool="swarm_report", args={"summary": "x"}, body_session_uuid=uuid, body_epoch=BODY_EPOCH,
                                      project_uid=world.ids["uid"], home_agent_id=world.ids["task"])
        with pytest.raises(HTTPException) as refused:
            asyncio.run(proxy_server.run(world.app, who, call))
        assert refused.value.status_code == 403 and refused.value.detail == {"code": "proxy_binding_refused"}
    assert len(_reports(world)) == 1


async def _async(value):
    return value


class RecordingLink:

    def __init__(self, capabilities=()) -> None:
        self.sent = []
        self._capabilities = list(capabilities)

    def client(self, install_id: str):
        return self if install_id == INSTALL_A else None

    def capabilities(self, install_id: str):
        return list(self._capabilities)

    async def request(self, method, path, json=None, timeout=None):
        self.sent.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {"result": {"content": []}})


def test_a_remote_bodys_task_manager_call_goes_to_the_home_in_the_state_names_an_older_build_reads(world):
    world.current["dir"] = world.dirs["B"]
    link = RecordingLink()
    peer_links.LINKS = link
    body = SimpleNamespace(session=SimpleNamespace(id="ses_body", tmux_created_epoch=BODY_EPOCH), tmux_session="carnivore_t1",
                           session_row_id=world.ids["body_row"])
    view = SimpleNamespace(list_session_infos=lambda: _async([body]))
    caller = AgentCaller(session_id="ses_body", tmux_name="carnivore_t1", current_session_id="ses_body")
    for name, args in (("task_manager_update", {"item": 3, "state": "review", "text": "review"}),
                       ("task_manager_batch_run", {"ops": [{"op": "update", "item": 3, "state": "waiting"}, {"op": "update", "item": 4, "state": "todo"}]}),
                       ("swarm_report", {"summary": "state review", "state": "review"})):
        asyncio.run(proxy_server.proxy_client.maybe_forward(view, caller, name, args))
    assert link.sent[0]["args"] == {"item": 3, "state": "done_by_claude", "text": "review"}
    assert [op["state"] for op in link.sent[1]["args"]["ops"]] == ["waiting_install", "back_burner"]
    assert link.sent[2]["args"] == {"summary": "state review", "state": "review"}
    assert [call["tool"] for call in link.sent] == ["huddle_update", "huddle_batch", "swarm_report"]


def test_a_home_that_advertises_the_task_manager_names_hears_them(world):
    world.current["dir"] = world.dirs["B"]
    link = RecordingLink(capabilities=["swarm.proxy", "task_manager.names"])
    peer_links.LINKS = link
    body = SimpleNamespace(session=SimpleNamespace(id="ses_body", tmux_created_epoch=BODY_EPOCH), tmux_session="carnivore_t1",
                           session_row_id=world.ids["body_row"])
    view = SimpleNamespace(list_session_infos=lambda: _async([body]))
    caller = AgentCaller(session_id="ses_body", tmux_name="carnivore_t1", current_session_id="ses_body")
    for name in ("task_manager_update", "task_manager_board_create", "swarm_report"):
        asyncio.run(proxy_server.proxy_client.maybe_forward(view, caller, name, {"item": 3}))
    assert [call["tool"] for call in link.sent] == ["task_manager_update", "task_manager_board_create", "swarm_report"]


def test_a_spawn_with_auto_distribute_off_stays_home(tmp_path):
    wired = FakeWired(tmp_path, a=snap("a", load1=3.0), b=snap("b", load1=0.5))
    work = resolve({"kind": "light"}, None)
    stays = asyncio.run(explain.place(explain.Request(work), wired=wired, record_it=False))
    assert stays.chosen == INSTALL_A
    named = asyncio.run(explain.place(explain.Request(work, machine="studio"), wired=wired, record_it=False))
    assert named.chosen == INSTALL_B
